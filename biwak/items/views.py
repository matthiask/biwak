import datetime as dt

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak import cursors, schedules
from biwak.accounts.models import User
from biwak.activity.operations import is_subscribed, subscribe, unsubscribe
from biwak.forms import Form, next_url
from biwak.items import glance, operations as ops, visibility
from biwak.items.models import Group, Item, Kind, Status, TodoList
from biwak.reactions.operations import prefetch


def item_for(request, pk, kind=None):
    """The item if the person may see it, else 404: the one check
    (specs/access.md)"""
    qs = Item.objects.visible_to(request.user).select_related("project", "parent")
    if kind:
        qs = qs.filter(kind=kind)
    return get_object_or_404(qs, pk=pk)


def assignable_people(item):
    """People who can see the item (clients only if it's visible to them)"""
    project = item.project
    people = User.objects.active().filter(memberships__project=project)
    if not item.is_client_visible:
        people = people.filter(is_client=False)
    return people.distinct()


class RepeatForm(Form):
    """The "Repeat" fields shared by the inline form and the to-do's page
    (specs/todos.md); ``cleaned_data["recurrence"]`` is the rule. Presets
    count from the due date (today without one); the form's due date is
    ``due_on``."""

    repeat = forms.ChoiceField(
        label=_("Repeat"),
        required=False,
        choices=schedules.preset_choices(),
        help_text=_("The next to-do is created when this one is completed."),
    )
    custom_rule = forms.CharField(
        label=_("Custom schedule"),
        required=False,
        max_length=200,
        help_text=_("An RRULE, e.g. FREQ=WEEKLY;BYDAY=MO,TH"),
    )
    recurrence_ends_on = forms.DateField(
        label=_("Repeats until"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    recurrence_count = forms.IntegerField(
        label=_("Repeats left"),
        required=False,
        min_value=1,
        help_text=_("How many more to-dos to create; empty: no limit."),
    )

    def _rule(self, data):
        repeat = data["repeat"]
        if repeat == schedules.CUSTOM:
            if not data.get("custom_rule"):
                raise schedules.InvalidRule(_("Enter the schedule."))
            return schedules.validate(data["custom_rule"])
        return schedules.from_preset(repeat, data.get("due_on") or schedules.today())

    def clean(self):
        data = super().clean()
        data["recurrence"] = ""
        if data.get("repeat"):
            try:
                data["recurrence"] = self._rule(data)
            except schedules.InvalidRule as exc:
                field = (
                    "custom_rule" if data["repeat"] == schedules.CUSTOM else "repeat"
                )
                self.add_error(field, str(exc))
        return data

    def recurrence_kwargs(self):
        data = self.cleaned_data
        return {
            "recurrence": data["recurrence"],
            "recurrence_ends_on": data["recurrence_ends_on"],
            "recurrence_count": data["recurrence_count"],
        }


class TodoForm(RepeatForm):
    """Adding a to-do from the list: inline, with everything a to-do has
    at first (specs/todos.md); without JavaScript a plain form"""

    title = forms.CharField(label=_("title"), max_length=500)
    notes = forms.CharField(
        label=_("notes"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    assignees = forms.ModelMultipleChoiceField(
        label=_("assignees"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    due_on = forms.DateField(
        label=_("due on"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    group = forms.IntegerField(required=False, widget=forms.HiddenInput)
    field_order = ["title", "notes", "assignees", "due_on", "group"]

    def __init__(self, *args, item, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignees"].queryset = assignable_people(item)


def wants_fragment(request):
    """The inline form (frontend/add-todo.js) wants the new row only"""
    return request.headers.get("X-Biwak-Fragment") == "1"


def _todos(todolist_item):
    return glance.with_signals(
        Item.objects
        .filter(parent=todolist_item, kind=Kind.TODO)
        .exclude(status=Status.TRASHED)
        .select_related("todo")
        .prefetch_related("todo__assignees")
    )


COMPLETED_FIRST = 20
COMPLETED_MORE = 50


def _completed_page(todos, *, size, before=None):
    """The next ``size`` completed to-dos, the latest first, after the cursor
    ``before`` (``biwak/cursors.py``, of the last one shown) and the
    cursor of the page after it, or ``None`` at the end."""
    todos = todos.filter(todo__completed_at__isnull=False)
    if before:
        try:
            at, pk = cursors.decode(before)
        except ValueError as error:
            raise Http404("Bad cursor") from error
        todos = todos.filter(
            Q(todo__completed_at__lt=at) | Q(todo__completed_at=at, pk__lt=pk)
        )
    rows = list(todos.order_by("-todo__completed_at", "-pk")[: size + 1])
    more = len(rows) > size
    rows = rows[:size]
    cursor = None
    if more:
        last = rows[-1]
        cursor = cursors.encode(last.todo.completed_at, last.pk)
    return rows, cursor


def completed_todos(request, pk):
    """The next page of a list's completed to-dos, for "Show more" (htmx)"""
    item = item_for(request, pk, Kind.LIST)
    rows, cursor = _completed_page(
        _todos(item), size=COMPLETED_MORE, before=request.GET.get("before")
    )
    return render(
        request,
        "items/_completed.html",
        {"item": item, "completed": rows, "cursor": cursor},
    )


def todolist(request, pk):
    item = item_for(request, pk, Kind.LIST)
    todolist = item.todolist
    todos = _todos(item)
    open_todos = todos.filter(todo__completed_at__isnull=True).order_by(
        "position", "pk"
    )
    completed_count = todos.filter(todo__completed_at__isnull=False).count()
    groups = list(todolist.groups.all())
    by_group = {None: []} | {g.pk: [] for g in groups}
    for todo in open_todos:
        by_group[todo.todo.group_id].append(todo)
    form = TodoForm(request.POST or None, item=item)
    if request.method == "POST":
        if not form.is_valid():
            if wants_fragment(request):
                return HttpResponse(
                    " ".join(e for errors in form.errors.values() for e in errors),
                    status=422,
                    content_type="text/plain; charset=utf-8",
                )
        else:
            data = form.cleaned_data
            group = None
            if group_id := data["group"]:
                group = get_object_or_404(Group, pk=group_id, todolist=todolist)
            todo = ops.create_todo(
                todolist=item,
                title=data["title"],
                creator=request.user,
                group=group,
                notes=data["notes"],
                due_on=data["due_on"],
                assignees=list(data["assignees"]),
                **form.recurrence_kwargs(),
            )
            if wants_fragment(request):
                return render(request, "items/_todo.html", {"todo": todo}, status=201)
            return redirect(item)
    view = request.GET.get("view") or todolist.view
    completed, completed_cursor = _completed_page(todos, size=COMPLETED_FIRST)
    return render(
        request,
        "items/todolist.html",
        {
            "item": item,
            "todolist": todolist,
            "ungrouped": by_group[None],
            "groups": [(g, by_group[g.pk]) for g in groups],
            "completed": completed,
            "completed_cursor": completed_cursor,
            "completed_count": completed_count,
            "form": form,
            "people": form.fields["assignees"].queryset,
            "view": view,
            "can_switch": item.has_switch and not request.user.is_client,
            "can_change": ops.can_change(request.user, item),
            "affected": visibility.affected(item)
            if item.has_switch and not item.is_client_visible
            else None,
        },
    )


@require_POST
def group_create(request, pk):
    item = item_for(request, pk, Kind.LIST)
    if title := request.POST.get("title", "").strip():
        ops.create_group(todolist=item.todolist, title=title[:200])
    return redirect(item)


@require_POST
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    item = item_for(request, group.todolist_id, Kind.LIST)
    ops.delete_group(group)
    return redirect(item)


@require_POST
def group_rename(request, pk):
    group = get_object_or_404(Group, pk=pk)
    item = item_for(request, group.todolist_id, Kind.LIST)
    if title := request.POST.get("title", "").strip():
        ops.rename_group(group, title=title[:200])
    return redirect(item)


@require_POST
def group_move(request, pk):
    """Dragging (quietly) or the up and down buttons (redirecting back)"""
    group = get_object_or_404(Group, pk=pk)
    item = item_for(request, group.todolist_id, Kind.LIST)
    ops.move_group(group, index=max(0, int(request.POST.get("index", 0))))
    if request.POST.get("quiet"):
        return HttpResponse(status=204)
    return redirect(item)


def _index(value):
    """A position, or None for the end"""
    return None if value in {None, "", "end"} else max(0, int(value))


@require_POST
def todo_move(request, pk):
    """Dragging (frontend/todos.js, quietly): into a list's group at an
    index. The to-do's page (keyboard): ``target`` is ``LIST`` or
    ``LIST:GROUP``, ``index`` 0 (the top) or empty (the end)."""
    item = item_for(request, pk, Kind.TODO)
    list_id, group_id = (
        request.POST.get("list", item.parent_id),
        request.POST.get("group"),
    )
    if target_value := request.POST.get("target"):
        list_id, _sep, group_id = target_value.partition(":")
    target = item_for(request, list_id, Kind.LIST)
    group = None
    if group_id:
        group = get_object_or_404(Group, pk=group_id, todolist=target.todolist)
    ops.move_todo(
        item,
        todolist=target,
        group=group,
        index=_index(request.POST.get("index")),
        actor=request.user,
    )
    if request.headers.get("HX-Request") or request.POST.get("quiet"):
        return HttpResponse(status=204)
    return redirect(item if target_value else target)


@require_POST
def todos_move(request, pk):
    """Dragging one or several to-dos (frontend/todos.js) into list ``pk``,
    a ``group`` (empty: ungrouped), next to each other at ``index`` among
    the others there; ``todos`` in their new order"""
    target = item_for(request, pk, Kind.LIST)
    try:
        ids = [int(value) for value in request.POST.getlist("todos")]
    except ValueError:
        return HttpResponse(status=400)
    todos = {
        todo.pk: todo
        for todo in Item.objects
        .visible_to(request.user)
        .filter(pk__in=ids, kind=Kind.TODO, project=target.project_id)
        .select_related("todo")
    }
    if not ids or len(todos) != len(set(ids)):
        return HttpResponse(status=404)
    group = None
    if group_id := request.POST.get("group"):
        group = get_object_or_404(Group, pk=group_id, todolist=target.todolist)
    ops.move_todos(
        [todos[pk] for pk in ids],
        todolist=target,
        group=group,
        index=_index(request.POST.get("index")),
        actor=request.user,
    )
    return HttpResponse(status=204)


@require_POST
def todo_toggle(request, pk):
    item = item_for(request, pk, Kind.TODO)
    if item.todo.is_completed:
        ops.reopen(item, actor=request.user)
    else:
        ops.complete(item, actor=request.user)
    return redirect(next_url(request) or item.parent)


class TodoDetailForm(RepeatForm):
    title = forms.CharField(label=_("title"), max_length=500)
    notes = forms.CharField(
        label=_("notes"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Markdown"),
    )
    due_on = forms.DateField(
        label=_("due on"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    assignees = forms.ModelMultipleChoiceField(
        label=_("assignees"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    field_order = ["title", "notes", "due_on", "assignees"]


class CommentForm(Form):
    content = forms.CharField(
        label=_("comment"), widget=forms.Textarea(attrs={"rows": 3})
    )


def todo(request, pk):
    item = item_for(request, pk, Kind.TODO)
    todo = item.todo
    people = assignable_people(item)
    preset = schedules.preset_for(todo.recurrence, todo.due_on or schedules.today())
    form = TodoDetailForm(
        request.POST if request.POST.get("form") == "todo" else None,
        initial={
            "title": item.title,
            "notes": todo.notes,
            "due_on": todo.due_on,
            "assignees": list(todo.assignees.all()),
            "repeat": preset,
            "custom_rule": todo.recurrence if preset == schedules.CUSTOM else "",
            "recurrence_ends_on": todo.recurrence_ends_on,
            "recurrence_count": todo.recurrence_count,
        },
    )
    form.fields["assignees"].queryset = people
    mentions_url = reverse("mentionable", args=[item.pk])
    for field in ["title", "notes"]:
        form.fields[field].widget.attrs["data-mentions"] = mentions_url
    if form.is_valid():
        data = form.cleaned_data
        ops.update_todo(
            item,
            actor=request.user,
            title=data["title"],
            notes=data["notes"],
            due_on=data["due_on"],
            assignees=data["assignees"],
            **form.recurrence_kwargs(),
        )
        return redirect(item)
    prefetch(item)
    comment_form = CommentForm(
        request.POST if request.POST.get("form") == "comment" else None
    )
    comment_form.fields["content"].widget.attrs["data-mentions"] = mentions_url
    if comment_form.is_valid():
        ops.add_comment(
            item, author=request.user, content=comment_form.cleaned_data["content"]
        )
        return redirect(f"{item.get_absolute_url()}#comments")
    return render(
        request,
        "items/todo.html",
        {
            "item": item,
            "todo": todo,
            "form": form,
            "comment_form": comment_form,
            "comments": item.comments.select_related("author"),
            "subscribers": [s.user for s in item.subscriptions.select_related("user")],
            "is_subscribed": is_subscribed(request.user, item),
            "move_targets": _move_targets(request, item),
            "can_change": ops.can_change(request.user, item),
            "today": dt.date.today(),
            "previous": _previous(request, todo),
        },
    )


def todo_peek(request, pk):
    """The notes in full and the latest comments below a row, without
    leaving the list (htmx, specs/glance.md); no forms"""
    item = item_for(request, pk, Kind.TODO)
    return render(
        request,
        "items/_peek.html",
        {
            "item": item,
            "todo": item.todo,
            "comments": glance.peek_comments(item),
            "comment_count": item.comments.count(),
        },
    )


def _previous(request, todo):
    """The to-do this one was created from, if the person sees it"""
    if todo.previous_id is None:
        return None
    return (
        Item.objects
        .visible_to(request.user)
        .filter(pk=todo.previous_id)
        .select_related("todo__completed_by")
        .first()
    )


def _move_targets(request, item):
    """The lists (and their groups) a to-do can move to, without dragging:
    the active lists of the project the person sees"""
    lists = (
        Item.objects
        .visible_to(request.user)
        .filter(
            project=item.project_id,
            kind=Kind.LIST,
            parent=None,
            status=Status.ACTIVE,
        )
        .prefetch_related("todolist__groups")
    )
    return [(target, list(target.todolist.groups.all())) for target in lists]


@require_POST
def subscription(request, pk):
    item = item_for(request, pk)
    if request.POST.get("subscribe"):
        subscribe(request.user, item)
    else:
        unsubscribe(request.user, item)
    return redirect(item)


@require_POST
def switch(request, pk):
    """The visibility switch, staff only"""
    if request.user.is_client:
        raise PermissionDenied
    item = item_for(request, pk)
    ops.set_visibility(
        item, visible=bool(request.POST.get("visible")), actor=request.user
    )
    return redirect(item)


@require_POST
def item_trash(request, pk):
    item = item_for(request, pk)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    ops.trash(item, actor=request.user)
    messages.success(
        request,
        _("“%(title)s” is in the trash for %(days)s days.")
        % {"title": item.title, "days": ops.TRASH_DAYS},
    )
    return redirect(item.parent or item.project)


@require_POST
def item_restore(request, pk):
    """From the project's trash, staff only"""
    if request.user.is_client:
        raise PermissionDenied
    item = get_object_or_404(
        Item.objects.visible_to(request.user, with_trashed=True), pk=pk
    )
    try:
        ops.restore(item, actor=request.user)
    except ValueError:
        messages.error(request, _("Restore what it was in first."))
        return redirect("project_trash", pk=item.project_id)
    return redirect(item)


@require_POST
def item_archive(request, pk):
    """Archives a list, or (``unarchive``) brings it back"""
    item = item_for(request, pk, Kind.LIST)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    if request.POST.get("unarchive"):
        ops.unarchive(item, actor=request.user)
    else:
        ops.archive(item, actor=request.user)
    return redirect(item)


class ListEditForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    description = forms.CharField(
        label=_("description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Markdown"),
    )
    view = forms.ChoiceField(
        label=_("Shown as"),
        choices=TodoList.View.choices,
        widget=forms.RadioSelect,
    )


def list_edit(request, pk):
    item = item_for(request, pk, Kind.LIST)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = ListEditForm(
        request.POST or None,
        initial={
            "title": item.title,
            "description": item.todolist.description,
            "view": item.todolist.view,
        },
    )
    if form.is_valid():
        ops.update_list(item, actor=request.user, **form.cleaned_data)
        return redirect(item)
    return render(request, "items/list_edit.html", {"item": item, "form": form})
