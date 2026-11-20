import datetime as dt

from django import forms
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.accounts.models import User
from biwak.activity.operations import is_subscribed, subscribe, unsubscribe
from biwak.forms import Form
from biwak.items import operations as ops, visibility
from biwak.items.models import Group, Item, Kind


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


class TodoForm(Form):
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

    def __init__(self, *args, item, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignees"].queryset = assignable_people(item)


def wants_fragment(request):
    """The inline form (frontend/add-todo.js) wants the new row only"""
    return request.headers.get("X-Biwak-Fragment") == "1"


def _todos(todolist_item):
    return (
        Item.objects
        .filter(parent=todolist_item, kind=Kind.TODO)
        .exclude(status="trashed")
        .select_related("todo")
        .prefetch_related("todo__assignees")
    )


def todolist(request, pk):
    item = item_for(request, pk, Kind.LIST)
    todolist = item.todolist
    todos = _todos(item)
    open_todos = todos.filter(todo__completed_at__isnull=True).order_by(
        "position", "pk"
    )
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
            )
            if wants_fragment(request):
                return render(request, "items/_todo.html", {"todo": todo}, status=201)
            return redirect(item)
    view = request.GET.get("view") or todolist.view
    return render(
        request,
        "items/todolist.html",
        {
            "item": item,
            "todolist": todolist,
            "ungrouped": by_group[None],
            "groups": [(g, by_group[g.pk]) for g in groups],
            "completed": todos.filter(todo__completed_at__isnull=False).order_by(
                "-todo__completed_at"
            )[:20],
            "form": form,
            "people": form.fields["assignees"].queryset,
            "view": view,
            "can_switch": item.has_switch and not request.user.is_client,
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
def group_move(request, pk):
    group = get_object_or_404(Group, pk=pk)
    item_for(request, group.todolist_id, Kind.LIST)
    ops.move_group(group, index=int(request.POST.get("index", 0)))
    return HttpResponse(status=204)


@require_POST
def todo_move(request, pk):
    """Dragging (frontend/todos.js): into a list's group at an index"""
    item = item_for(request, pk, Kind.TODO)
    target = item_for(request, request.POST.get("list", item.parent_id), Kind.LIST)
    group = None
    if group_id := request.POST.get("group"):
        group = get_object_or_404(Group, pk=group_id, todolist=target.todolist)
    ops.move_todo(
        item,
        todolist=target,
        group=group,
        index=int(request.POST.get("index", 0)),
        actor=request.user,
    )
    if request.headers.get("HX-Request") or request.POST.get("quiet"):
        return HttpResponse(status=204)
    return redirect(target)


@require_POST
def todo_toggle(request, pk):
    item = item_for(request, pk, Kind.TODO)
    if item.todo.is_completed:
        ops.reopen(item, actor=request.user)
    else:
        ops.complete(item, actor=request.user)
    return redirect(request.POST.get("next") or item.parent)


class TodoDetailForm(Form):
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


class CommentForm(Form):
    content = forms.CharField(
        label=_("comment"), widget=forms.Textarea(attrs={"rows": 3})
    )


def todo(request, pk):
    item = item_for(request, pk, Kind.TODO)
    todo = item.todo
    people = assignable_people(item)
    form = TodoDetailForm(
        request.POST if request.POST.get("form") == "todo" else None,
        initial={
            "title": item.title,
            "notes": todo.notes,
            "due_on": todo.due_on,
            "assignees": list(todo.assignees.all()),
        },
    )
    form.fields["assignees"].queryset = people
    if form.is_valid():
        data = form.cleaned_data
        ops.update_todo(
            item,
            actor=request.user,
            title=data["title"],
            notes=data["notes"],
            due_on=data["due_on"],
            assignees=data["assignees"],
        )
        return redirect(item)
    comment_form = CommentForm(
        request.POST if request.POST.get("form") == "comment" else None
    )
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
            "today": dt.date.today(),
        },
    )


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
    ops.trash(item, actor=request.user)
    return redirect(item.parent or item.project)
