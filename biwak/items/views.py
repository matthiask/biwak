from django import forms
from django.contrib import messages
from django.core.exceptions import BadRequest, PermissionDenied
from django.db.models import Q
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _, ngettext
from django.views.decorators.http import require_POST

from biwak import checklists, cursors, schedules
from biwak.accounts.models import User
from biwak.activity import timeline as timelines
from biwak.activity.operations import (
    StillAssigned,
    is_assigned,
    is_subscribed,
    subscribe,
    unsubscribe,
)
from biwak.forms import Form, PeopleField, next_url
from biwak.items import editing, glance, operations as ops, visibility
from biwak.items.models import Comment, Group, Item, Kind, Status, TodoList
from biwak.modals import form_response
from biwak.reactions.operations import prefetch
from biwak.schedules_forms import (
    KEEP,
    EndsCountInput,
    EndsOnInput,
    RuleField,
    RuleFormMixin,
)


def item_for(request, pk, kind=None, *, drafts=False):
    """The item if the person may see it, else 404: the one check
    (specs/access.md), for the pages and the API; ``drafts``: the
    person's own drafts too (the editor's pages)"""
    qs = Item.objects.visible_to(request.user, drafts=drafts).select_related(
        "project", "parent", "creator"
    )
    if kind:
        qs = qs.filter(kind=kind)
    return get_object_or_404(qs, pk=pk)


def comment_for(request, pk):
    """The comment if the person may see its item, else 404: the same check
    as ``item_for()``"""
    return get_object_or_404(
        Comment.objects.filter(
            item__in=Item.objects.visible_to(request.user)
        ).select_related("item", "item__project"),
        pk=pk,
    )


class RepeatForm(RuleFormMixin, Form):
    """The "Repeat" fields shared by the inline form and the to-do's page
    (specs/todos.md, specs/rule-widget.md); ``cleaned_data["recurrence"]``
    is the rule. A rule the widget can't show stays as it is (``initial``).
    The widget starts from the due date (today without one)."""

    recurrence = RuleField(
        label=_("Repeat"),
        help_text=_("The next to-do is created when this one is completed."),
    )
    # Rendered inside the rule widget's fieldset (forms/rule_widget.html)
    recurrence_ends_on = forms.DateField(
        label=_("Repeats until"),
        required=False,
        widget=EndsOnInput(),
    )
    recurrence_count = forms.IntegerField(
        label=_("Repeats left"),
        required=False,
        min_value=1,
        widget=EndsCountInput(),
        help_text=_("How many more to-dos to create; empty: no limit."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self.fields["recurrence"].widget
        widget.anchor = self.initial.get("due_on") or schedules.today()
        widget.ends = self.ends()

    def ends(self, *, posted=True):
        """The end date and count as the rule widget shows them: what was
        posted (``posted``) or the initial values"""

        def shown(name):
            field = self[name]
            value = field.value() if posted else field.initial
            return value.isoformat() if hasattr(value, "isoformat") else value or ""

        return {"on": shown("recurrence_ends_on"), "count": shown("recurrence_count")}

    def clean(self):
        data = super().clean()
        if data.get("recurrence") is KEEP:
            data["recurrence"] = self.initial.get("recurrence", "")
        return data

    def recurrence_kwargs(self):
        data = self.cleaned_data
        return {
            "recurrence": data["recurrence"],
            "recurrence_ends_on": data["recurrence_ends_on"],
            "recurrence_count": data["recurrence_count"],
        }


class TodoFieldsForm(RepeatForm):
    """A to-do's fields, for adding one (``TodoForm``) and on its page
    (``TodoDetailForm``); ``item`` is the to-do or its list"""

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
    assignees = PeopleField(label=_("assignees"), queryset=User.objects.none())

    def __init__(self, *args, item, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignees"].queryset = ops.assignable_people(item, user)
        # Teams add their members (specs/teams.md)
        self.fields["assignees"].offer_teams(
            project=item.project, visible=item.is_client_visible
        )


class TodoForm(TodoFieldsForm):
    """Adding a to-do from the list: inline, with everything a to-do has
    at first (specs/todos.md); without JavaScript a plain form"""

    group = forms.IntegerField(required=False, widget=forms.HiddenInput)
    field_order = ["title", "notes", "assignees", "due_on", "group"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notes"].widget.attrs["rows"] = 3
        self.fields["notes"].help_text = ""


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
    form = TodoForm(request.POST or None, item=item, user=request.user)
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
            "all_done": bool(completed_count) and not any(by_group.values()),
            "form": form,
            "people": form.fields["assignees"].queryset,
            "people_teams": form.fields["assignees"].widget.team_attrs(),
            "view": view,
            "can_switch": item.has_switch and not request.user.is_client,
            "can_change": ops.can_change(request.user, item),
        },
    )


def changeable_list(request, pk):
    """The list if the person may change it and its groups: clients only
    lists they created (``can_change()``, 403); for the pages and the API"""
    item = item_for(request, pk, Kind.LIST)
    if not ops.can_change(request.user, item):
        raise PermissionDenied(_("You can only change lists you created."))
    return item


def changeable_group(request, pk):
    """The group and its list, changed like the list"""
    group = get_object_or_404(Group, pk=pk)
    return group, changeable_list(request, group.todolist_id)


class GroupForm(Form):
    title = forms.CharField(label=_("title"), max_length=200)


def group_create(request, pk):
    """A new group: a modal on the list's page, also a page of its own"""
    item = changeable_list(request, pk)
    form = GroupForm(request.POST or None)
    if form.is_valid():
        ops.create_group(todolist=item.todolist, title=form.cleaned_data["title"])
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("New group"),
        item=item,
        parent=item,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Add group"),
    )


@require_POST
def group_delete(request, pk):
    group, item = changeable_group(request, pk)
    ops.delete_group(group)
    return redirect(item)


def group_rename(request, pk):
    """Renaming a group: a modal on the list's page, also a page"""
    group, item = changeable_group(request, pk)
    form = GroupForm(request.POST or None, initial={"title": group.title})
    if form.is_valid():
        ops.rename_group(group, title=form.cleaned_data["title"])
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("Rename the group"),
        item=item,
        parent=item,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Rename"),
    )


@require_POST
def group_move(request, pk):
    """Dragging (quietly) or the up and down buttons (redirecting back)"""
    group, item = changeable_group(request, pk)
    ops.move_group(group, index=_index(request.POST.get("index", 0)) or 0)
    if request.POST.get("quiet"):
        return HttpResponse(status=204)
    return redirect(item)


def _number(value):
    """A number posted (an ID, an index); 400 for anything else"""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"Not a number: {value!r}") from exc


def _index(value):
    """A position, or None for the end"""
    return None if value in {None, "", "end"} else max(0, _number(value))


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
    target = item_for(request, _number(list_id), Kind.LIST)
    if target.project_id != item.project_id:
        # To-dos stay in their project
        return HttpResponse(status=400)
    group = None
    if group_id:
        group = get_object_or_404(Group, pk=_number(group_id), todolist=target.todolist)
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


class MoveTodoForm(Form):
    """Moving a to-do without dragging: the list or one of its groups, and
    where in it"""

    target = forms.ChoiceField(label=_("List and group"))
    index = forms.ChoiceField(
        label=_("Position"),
        choices=[("0", _("To the top")), ("end", _("To the end"))],
        initial="end",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, targets, **kwargs):
        super().__init__(*args, **kwargs)
        choices = []
        for target, groups in targets:
            label = str(target)
            if target.is_client_visible:
                label += f" ({_('clients can see this')})"
            choices.append((
                label,
                [
                    (str(target.pk), str(target)),
                    *((f"{target.pk}:{g.pk}", f"{target} / {g}") for g in groups),
                ],
            ))
        self.fields["target"].choices = choices


def todo_move_to(request, pk):
    """Moving a to-do to a list or group: a modal on its page, also a page"""
    item = item_for(request, pk, Kind.TODO)
    if item.todo.is_completed:
        raise Http404
    todo = item.todo
    initial = f"{item.parent_id}:{todo.group_id}" if todo.group_id else item.parent_id
    form = MoveTodoForm(
        request.POST or None,
        targets=_move_targets(request, item),
        initial={"target": str(initial)},
    )
    if form.is_valid():
        list_id, _sep, group_id = form.cleaned_data["target"].partition(":")
        target = item_for(request, int(list_id), Kind.LIST)
        group = None
        if group_id:
            group = get_object_or_404(Group, pk=int(group_id), todolist=target.todolist)
        ops.move_todo(
            item,
            todolist=target,
            group=group,
            index=_index(form.cleaned_data["index"]),
            actor=request.user,
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("Move to…"),
        item=item,
        parent=item.parent,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Move"),
    )


def todos_to_move(request, target, ids):
    """The to-dos by ID, for moving into the list ``target``: 404 unless
    the person sees them all, 400 for to-dos of another project (the pages
    and the API)"""
    todos = {
        todo.pk: todo
        for todo in Item.objects
        .visible_to(request.user)
        .filter(pk__in=ids, kind=Kind.TODO)
        .select_related("todo")
    }
    if not ids or len(todos) != len(set(ids)):
        raise Http404(_("Not all of these to-dos were found."))
    if any(todo.project_id != target.project_id for todo in todos.values()):
        raise BadRequest(_("To-dos can't move to another project."))
    return todos


@require_POST
def todos_move(request, pk):
    """Dragging one or several to-dos (frontend/todos.js) into list ``pk``,
    a ``group`` (empty: ungrouped), next to each other at ``index`` among
    the others there; ``todos`` in their new order"""
    target = item_for(request, pk, Kind.LIST)
    ids = [_number(value) for value in request.POST.getlist("todos")]
    todos = todos_to_move(request, target, ids)
    group = None
    if group_id := request.POST.get("group"):
        group = get_object_or_404(Group, pk=_number(group_id), todolist=target.todolist)
    try:
        ops.move_todos(
            [todos[pk] for pk in ids],
            todolist=target,
            group=group,
            index=_index(request.POST.get("index")),
            actor=request.user,
        )
    except ValueError:
        return HttpResponse(status=400)
    return HttpResponse(status=204)


@require_POST
def todo_toggle(request, pk):
    """Completes (``done=1``) or reopens (``done=0``) a to-do: what the
    button said, so a page from before someone else's change doesn't undo
    it; already so, nothing happens"""
    item = item_for(request, pk, Kind.TODO)
    done = request.POST.get("done")
    if done not in {"0", "1"}:
        return HttpResponse(status=400)
    if done == "1" and not item.todo.is_completed:
        ops.complete(item, actor=request.user)
    elif done == "0" and item.todo.is_completed:
        ops.reopen(item, actor=request.user)
    return redirect(next_url(request) or item.parent)


class TodoDetailForm(TodoFieldsForm):
    field_order = ["title", "notes", "due_on", "assignees"]

    def __init__(self, *args, item, user, **kwargs):
        super().__init__(*args, item=item, user=user, **kwargs)
        # Who can't be assigned anymore but still is (a client on a to-do
        # made internal) is offered too, so saving never drops anybody
        # silently: they stay unless taken out
        self.fields["assignees"].queryset = ops.assignable_or_assigned(item, user)


class CommentForm(Form):
    content = forms.CharField(
        label=_("Comment"), widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The "Comments" heading is right above the field
        self.fields["content"].hide_label = True


def todo(request, pk, *, edit=False):
    """The to-do's page: the to-do to read, or with ``edit`` (its own URL,
    also a posted form) the form in place of the text; the page's htmx
    takes the same region out of either (specs/ui.md, "Click to edit")"""
    item = item_for(request, pk, Kind.TODO)
    todo = item.todo
    edit = edit or request.POST.get("form") == "todo"
    form = TodoDetailForm(
        request.POST if request.POST.get("form") == "todo" else None,
        initial={
            "title": item.title,
            "notes": todo.notes,
            "due_on": todo.due_on,
            "assignees": list(todo.assignees.all()),
            "recurrence": todo.recurrence,
            "recurrence_ends_on": todo.recurrence_ends_on,
            "recurrence_count": todo.recurrence_count,
        },
        item=item,
        user=request.user,
    )
    mentions_url = reverse("mentionable", args=[item.pk])
    for field in ["title", "notes"]:
        form.fields[field].widget.attrs["data-mentions"] = mentions_url
    base = request.POST.get("base") or editing.version(item)
    if form.is_valid():
        data = form.cleaned_data
        try:
            ops.update_todo(
                item,
                actor=request.user,
                title=data["title"],
                notes=data["notes"],
                due_on=data["due_on"],
                assignees=data["assignees"],
                base=request.POST.get("base"),
                **form.recurrence_kwargs(),
            )
        except editing.StaleEdit as exc:
            form.add_error(
                None,
                editing.stale_message(request.user, item.project, exc.who, exc.when),
            )
        else:
            return redirect(item)
    if edit:
        # Shown now: nobody ticks the text meanwhile (specs/editor.md)
        editing.start(item, request.user)
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
            "edit": edit,
            "can_edit": True,
            "base": base,
            "comment_form": comment_form,
            "timeline": timelines.entries_for(
                item, request.user, item.comments.select_related("author")
            ),
            # Clients only learn about the project's members
            "subscribers": item.project.people_known_to(
                request.user,
                [s.user for s in item.subscriptions.select_related("user")],
            ),
            "is_subscribed": is_subscribed(request.user, item),
            "is_assigned": is_assigned(request.user, item),
            "move_targets": _move_targets(request, item),
            "can_change": ops.can_change(request.user, item),
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
    if request.POST.get("unassign"):
        # "You're assigned, so you hear about it": the way out is
        # unassigning oneself
        if is_assigned(request.user, item):
            ops.unassign(item, [request.user], actor=request.user)
    elif request.POST.get("subscribe"):
        subscribe(request.user, item)
    else:
        try:
            unsubscribe(request.user, item)
        except StillAssigned as exc:
            return HttpResponseBadRequest(str(exc))
    return redirect(item)


def _show_texts(item):
    """The question's title and what showing the item to clients makes
    visible (``visibility.affected()``)"""
    affected = visibility.affected(item)
    clients = ngettext("%(count)d client", "%(count)d clients", affected["clients"]) % {
        "count": affected["clients"]
    }
    values = {"comments": affected["comments"], "clients": clients}
    match item.kind:
        case Kind.LIST:
            title = _("Show this list to clients?")
            intro = ngettext(
                "Makes this list, %(count)d to-do and %(comments)d comments visible to %(clients)s.",
                "Makes this list, %(count)d to-dos and %(comments)d comments visible to %(clients)s.",
                affected["items"],
            ) % {"count": affected["items"], **values}
        case Kind.QUESTION:
            title = _("Show this check-in to clients?")
            intro = (
                _(
                    "Makes the check-in, its answers and their comments visible to %(clients)s."
                )
                % values
            )
        case _:
            title = {
                Kind.MESSAGE: _("Show this message to clients?"),
                Kind.FOLDER: _("Show this folder to clients?"),
                Kind.DOC: _("Show this doc to clients?"),
                Kind.FILE: _("Show this file to clients?"),
            }[item.kind]
            intro = _(
                "Makes it, %(items)d items below it and %(comments)d comments visible to %(clients)s."
            ) % {"items": affected["items"], **values}
    return title, intro


class ShowForm(forms.Form):
    """Only carries the switch's value"""

    visible = forms.CharField(widget=forms.HiddenInput, initial="1")


def switch(request, pk):
    """The visibility switch, staff only. Showing something to clients asks
    first (a modal, also a page: it can reveal what shouldn't be revealed),
    hiding it again is one click"""
    if request.user.is_client:
        raise PermissionDenied
    item = item_for(request, pk)
    if not item.has_switch:
        return HttpResponse(status=400)
    if request.method == "GET":
        if item.is_client_visible:
            return redirect(next_url(request) or item)
        title, intro = _show_texts(item)
        return form_response(
            request,
            ShowForm(),
            title=title,
            intro=intro,
            help_page="clients",
            item=item,
            cancel_url=next_url(request) or item.get_absolute_url(),
            submit_label=_("Show to clients"),
            destructive=True,
        )
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    ops.set_visibility(
        item, visible=bool(request.POST.get("visible")), actor=request.user
    )
    # Back to the grid when switched from a tile's menu
    return redirect(next_url(request) or item)


@require_POST
def tick(request, pk):
    """Ticks a checkbox of the item's text, or of one of its comments
    (``comment``), without opening the editor (specs/editor.md): ``index``
    is the checkbox, ``version`` the hash of the text the page showed, so
    the text changed since: 409 and the page reloads. ``checked`` sets the
    box (1 or 0), so a repeated click can't flip it back. Answers with the
    new version."""
    from biwak.files.operations import DocReadOnly

    item = item_for(request, pk)
    comment = None
    if request.POST.get("comment"):
        comment = get_object_or_404(Comment, pk=request.POST["comment"], item=item)
    try:
        index = int(request.POST["index"])
    except KeyError, ValueError:
        raise BadRequest("index") from None
    checked = {"1": True, "0": False}.get(request.POST.get("checked"))
    try:
        text = ops.tick(
            item,
            actor=request.user,
            index=index,
            version=request.POST.get("version", ""),
            comment=comment,
            checked=checked,
        )
    except editing.BeingEdited as exc:
        return _refused(
            editing.being_edited_message(request.user, item.project, exc.users)
        )
    except ops.ChecklistConflict as exc:
        return _refused(
            editing.changed_message(request.user, item.project, exc.who, exc.when),
            reload=True,
        )
    except DocReadOnly:
        # Made read-only since the page was shown: its boxes are disabled now
        return _refused("", reload=True)
    except checklists.NoCheckbox:
        raise BadRequest("index") from None
    return JsonResponse({"version": checklists.text_hash(text)})


def _refused(message, *, reload=False):
    """A tick that didn't happen: ``reload`` says the page's text is old"""
    return JsonResponse({"message": str(message), "reload": reload}, status=409)


@require_POST
def item_editing(request, pk):
    """The item's edit form is open (renewed every minute, frontend/editing.js)
    or, with ``release``, closed; while it's open nobody ticks the item's
    text (specs/editor.md)"""
    item = item_for(request, pk)
    if item.kind not in editing.EDITABLE or not ops.can_tick(request.user, item):
        raise PermissionDenied
    if request.POST.get("release"):
        editing.stop(item, request.user)
    else:
        editing.start(item, request.user)
    return HttpResponse(status=204)


def item_trash(request, pk):
    """Moving an item to the trash: asks first (a modal, also a page),
    the POST does it"""
    item = item_for(request, pk)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    if request.method != "POST":
        return form_response(
            request,
            None,
            title=_("Move to the trash?"),
            intro=_("It can be restored for %(days)s days.") % {"days": ops.TRASH_DAYS},
            item=item,
            cancel_url=next_url(request) or item.get_absolute_url(),
            submit_label=_("Move to the trash"),
            destructive=True,
        )
    ops.trash(item, actor=request.user)
    messages.success(
        request,
        _("“%(title)s” is in the trash for %(days)s days.")
        % {"title": item.title, "days": ops.TRASH_DAYS},
    )
    return redirect(next_url(request) or item.parent or item.project)


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
    return redirect(next_url(request) or item)


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
    # A modal, also a page (AGENTS.md); archiving and the trash are in the
    # list's "More" menu
    return form_response(
        request,
        form,
        title=_("Edit the list"),
        item=item,
        parent=item,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Save"),
    )
