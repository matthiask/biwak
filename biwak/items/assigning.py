"""Changing several to-dos at once: the selection's "Assign…", "Move…" and
"Due date…" on the to-dos page and a list's page (specs/handover.md)"""

from django import forms
from django.db import transaction
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext, gettext_lazy as _, ngettext

from biwak.accounts.models import User
from biwak.forms import Form, PeopleField, next_url
from biwak.items import operations as ops
from biwak.items.across import Confirming, ProjectChoice, _names
from biwak.items.models import Group, Item, Kind, Status
from biwak.items.views import MoveTodoForm, _index, item_for
from biwak.modals import form_response
from biwak.projects.models import Project


def ids_of(values):
    """The to-dos' IDs of a selection (``items``), 404 for anything else"""
    if not values or not all(str(value).isdecimal() for value in values):
        raise Http404
    return list(dict.fromkeys(int(value) for value in values))


def todos_for(user, ids):
    """``(to-dos, missing)``: the to-dos among ``ids`` the person sees (and
    so may assign, to-dos are shared work), in their order, and how many of
    the others aren't there for them (trashed, made internal, another
    project's, not to-dos)"""
    found = {
        item.pk: item
        for item in Item.objects
        .visible_to(user)
        .filter(pk__in=ids, kind=Kind.TODO)
        .select_related("project", "todo", "parent")
    }
    return [found[pk] for pk in ids if pk in found], len(set(ids) - set(found))


def missing_message(missing):
    return ngettext(
        "%(count)s of the selected to-dos can't be changed by you: it was"
        " trashed or you can't see it anymore. Nothing was changed.",
        "%(count)s of the selected to-dos can't be changed by you: they were"
        " trashed or you can't see them anymore. Nothing was changed.",
        missing,
    ) % {"count": missing}


class AssignForm(Form):
    people = PeopleField(label=_("people"), queryset=User.objects.none(), required=True)
    replace = forms.BooleanField(
        label=_("Instead of the current assignees"),
        required=False,
        help_text=_("Off: the people are added to those assigned already."),
    )

    def __init__(self, *args, todos, user, **kwargs):
        super().__init__(*args, **kwargs)
        # Only who can be assigned to every one of them
        self.fields["people"].queryset = (
            ops.assignable_to_all(todos, user) if todos else User.objects.none()
        )
        # Teams add their members (specs/teams.md)
        projects = {todo.project for todo in todos}
        self.fields["people"].offer_teams(
            project=projects.pop() if len(projects) == 1 else None,
            visible=all(todo.is_client_visible for todo in todos),
        )


def _selected(request):
    """The selected to-dos (``items``) the person sees, how many are missing,
    404 when there's none"""
    todos, missing = todos_for(request.user, ids_of(request.GET.getlist("items")))
    if not todos:
        raise Http404
    return todos, missing


def _refuse(form, message):
    """The form says why nothing changes, also before posting"""
    form.is_valid()
    if not form.is_bound:
        form.cleaned_data = {}
    form.add_error(None, message)


def _refuse_missing(form, missing):
    """All or nothing: with to-dos gone meanwhile, the form says so, also
    before posting, and nothing changes. True when it refused."""
    if missing:
        _refuse(form, missing_message(missing))
    return bool(missing)


def _intro(todos):
    if len(todos) == 1:
        return f"“{todos[0].title}”"
    return _("%(count)s to-dos") % {"count": len(todos)}


def _project(todos):
    """Their project when they're all in one (the client banner)"""
    return todos[0].project if len({t.project_id for t in todos}) == 1 else None


def todos_assign(request):
    """ "Assign…" for the selected to-dos (``items``, in the query): a modal,
    also a page. All or nothing: to-dos the person can't change (gone
    meanwhile) or somebody who can't be assigned to one of them change
    nothing, the form says how many and why."""
    todos, missing = _selected(request)
    form = AssignForm(
        request.POST if request.method == "POST" else None,
        todos=todos,
        user=request.user,
    )
    if not _refuse_missing(form, missing) and form.is_valid():
        try:
            ops.assign_todos(
                todos,
                form.cleaned_data["people"],
                actor=request.user,
                replace=form.cleaned_data["replace"],
            )
        except ops.AssignRefused as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(next_url(request) or "todos")
    return form_response(
        request,
        form,
        title=_("Assign…"),
        intro=_intro(todos),
        project=_project(todos),
        cancel_url=next_url(request) or "/todos/",
        submit_label=_("Assign"),
    )


# The choice of "Move…" making a new list in the project (staff)
NEW_LIST = "new"


class MoveForm(Confirming):
    """ "Move…": the project (staff; clients move within it), then a list
    of it or one of its groups, or a new list, and where in it. ``shown``:
    the project whose lists the form showed; choosing another shows its
    lists first."""

    project = ProjectChoice(Project.objects.none(), label=_("project"))
    shown = forms.CharField(widget=forms.HiddenInput, required=False)
    target = forms.ChoiceField(label=_("List and group"))
    index = MoveTodoForm.base_fields["index"]

    def __init__(self, *args, projects, targets, new_list, modal, **kwargs):
        super().__init__(*args, **kwargs)
        if projects is None:
            del self.fields["project"]
        else:
            self.fields["project"].queryset = projects
            if modal:
                # Another project shows its lists at once (htmx posts the
                # form, the view answers with the project's lists)
                self.fields["project"].widget.attrs |= {
                    "hx-post": modal,
                    "hx-target": "#modal",
                    "hx-headers": '{"HX-Modal": "true"}',
                    "hx-trigger": "change",
                }
        choices = MoveTodoForm(targets=targets).fields["target"].choices
        if new_list:
            choices = [*choices, (NEW_LIST, _("New list"))]
        self.fields["target"].choices = choices


def move_projects(user):
    """The projects the person may move the to-dos to: staff the active
    projects they open (decided 2026-11-22: moving across projects is
    staff only), clients none (the to-dos' own); None for clients"""
    if user.is_client:
        return None
    return Project.objects.accessible_to(user).active().order_by(Lower("name"), "pk")


def list_targets(user, project):
    """The lists (and their groups) of ``project`` the person sees, as for
    a to-do's "Move to…" (``views._move_targets()``)"""
    if project is None:
        return []
    lists = (
        Item.objects
        .visible_to(user)
        .filter(project=project, kind=Kind.LIST, parent=None, status=Status.ACTIVE)
        .prefetch_related("todolist__groups")
    )
    return [(target, list(target.todolist.groups.all())) for target in lists]


def new_list_title(todos):
    """The title of a new list for the moved to-dos (renamed later): their
    list's when they all come from one, else "Moved to-dos"
    (specs/decisions-to-confirm.md)"""
    lists = {todo.parent_id: todo.parent for todo in todos}
    if len(lists) == 1:
        return next(iter(lists.values())).title
    return gettext("Moved to-dos")


def new_list_visible(todos):
    """Whether a new list for the moved to-dos is visible to clients: when
    every list they come from is (decided 2026-11-23)"""
    return all(todo.parent.is_client_visible for todo in todos)


def hidden_note(todos, visible):
    """What moving the to-dos into an internal list hides from clients, as
    a sentence (empty when the list is visible or hides nothing)"""
    count = 0 if visible else sum(todo.is_client_visible for todo in todos)
    if not count:
        return ""
    return ngettext(
        "Clients won't see %(count)d to-do any more: the list is internal.",
        "Clients won't see %(count)d to-dos any more: the list is internal.",
        count,
    ) % {"count": count}


def move_notes(todos, project, visible, viewer):
    """Who moving the to-dos into a list of ``project`` adds there and who
    it drops, as sentences (empty when nobody)"""
    added, dropped = (
        list(people)
        for people in ops.todos_move_people(todos, project, visible=visible)
    )
    source = todos[0].project
    notes = []
    if added:
        notes.append(
            ngettext(
                "%(names)s will be added to %(project)s.",
                "%(names)s will be added to %(project)s.",
                len(added),
            )
            % {"names": _names(added, source, viewer), "project": project}
        )
    if dropped:
        notes.append(
            ngettext(
                "%(names)s won't see the to-dos in %(project)s: they'll be"
                " unassigned and unsubscribed.",
                "%(names)s won't see the to-dos in %(project)s: they'll be"
                " unassigned and unsubscribed.",
                len(dropped),
            )
            % {"names": _names(dropped, source, viewer), "project": project}
        )
    return " ".join(notes)


def todos_move(request):
    """ "Move…" for the selected to-dos: a list of a project or one of its
    groups, or a new list, and where in it (``ops.move_todos_to()``, next
    to each other in their order). Staff move into other projects too,
    after the form said who's added and dropped there (like "Move to…" of
    lists); clients within the to-dos' project. All or nothing, like
    "Assign…"."""
    todos, missing = _selected(request)
    own = _project(todos)
    projects = move_projects(request.user)
    post = request.POST if request.method == "POST" else None
    chosen = own or todos[0].project
    if projects is not None and post and (pk := post.get("project", "")).isdecimal():
        chosen = projects.filter(pk=pk).first() or chosen
    modal = request.get_full_path() if request.headers.get("HX-Modal") else ""

    def make(data):
        return MoveForm(
            data,
            projects=projects,
            targets=list_targets(request.user, chosen),
            new_list=ops.can_create(request.user, Kind.LIST),
            modal=modal,
            initial={"project": chosen, "shown": chosen.pk},
        )

    form = make(post)
    note = clients_note = ""
    if _refuse_missing(form, missing):
        pass
    elif projects is None and own is None:
        _refuse(form, several_projects_message())
    elif post is not None and post.get("shown", str(chosen.pk)) != str(chosen.pk):
        # Another project chosen: its lists first, nothing moves yet
        form = make(None)
    elif form.is_valid():
        value = form.cleaned_data["target"]
        if value == NEW_LIST:
            target, group = None, None
            visible = new_list_visible(todos)
        else:
            list_id, _sep, group_id = value.partition(":")
            target = item_for(request, int(list_id), Kind.LIST)
            group = None
            if group_id:
                group = get_object_or_404(
                    Group, pk=int(group_id), todolist=target.todolist
                )
            visible = target.is_client_visible
        note = move_notes(todos, chosen, visible, request.user)
        clients_note = hidden_note(todos, visible)
        if not (note or clients_note) or form.asked(f"{chosen.pk}:{value}"):
            try:
                with transaction.atomic():
                    if target is None:
                        target = ops.create_list(
                            project=chosen,
                            title=new_list_title(todos),
                            creator=request.user,
                            visible=visible,
                        )
                    ops.move_todos_to(
                        todos,
                        todolist=target,
                        group=group,
                        index=_index(form.cleaned_data["index"]),
                        actor=request.user,
                    )
            except ValueError as exc:
                form.add_error(None, str(exc))
                note = clients_note = ""
            else:
                return redirect(next_url(request) or "todos")
    return form_response(
        request,
        form,
        title=_("Move…"),
        intro=_intro(todos),
        project=own,
        cancel_url=next_url(request) or "/todos/",
        submit_label=_("Move"),
        template="items/across_form.html",
        destructive=bool(clients_note),
        extra={"note": note, "clients_note": clients_note},
    )


def several_projects_message():
    return _(
        "The selected to-dos are in several projects: to-dos move to the"
        " lists of their own project."
    )


class DatesForm(Form):
    """What "Due date…" does: the choices of copying a list, "Keep" being
    one date for all here; each field shown only with its choice
    (``shown_for``, frontend/shown-for.js)"""

    dates = forms.ChoiceField(
        label=_("Due dates"),
        choices=[
            (ops.Dates.KEEP, _("Set a date")),
            (ops.Dates.SHIFT, ops.Dates.SHIFT.label),
            (ops.Dates.REMOVE, ops.Dates.REMOVE.label),
        ],
        initial=ops.Dates.KEEP,
        widget=forms.RadioSelect,
    )
    due_on = forms.DateField(
        label=_("Due date"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    days = forms.IntegerField(
        label=_("Days"),
        required=False,
        min_value=-3650,
        max_value=3650,
        help_text=_("For “Move by”: negative numbers move them earlier."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_on"].shown_for = f"dates={ops.Dates.KEEP.value}"
        self.fields["days"].shown_for = f"dates={ops.Dates.SHIFT.value}"

    def clean(self):
        data = super().clean()
        choice = data.get("dates")
        if (
            choice == ops.Dates.KEEP
            and not data.get("due_on")
            and "due_on" not in self.errors
        ):
            self.add_error("due_on", self.fields["due_on"].error_messages["required"])
        if (
            choice == ops.Dates.SHIFT
            and not data.get("days")
            and "days" not in self.errors
        ):
            self.add_error("days", _("By how many days?"))
        return data


def todos_dates(request):
    """ "Due date…" for the selected to-dos: one due date for all, moved by
    a number of days, or removed (``ops.date_todos()``). All or nothing,
    like "Assign…"."""
    todos, missing = _selected(request)
    form = DatesForm(request.POST if request.method == "POST" else None)
    if not _refuse_missing(form, missing) and form.is_valid():
        data = form.cleaned_data
        try:
            ops.date_todos(
                todos,
                actor=request.user,
                dates=data["dates"],
                due_on=data["due_on"],
                days=data["days"] or 0,
            )
        except ops.InvalidDates as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(next_url(request) or "todos")
    return form_response(
        request,
        form,
        title=_("Due date…"),
        intro=_intro(todos),
        project=_project(todos),
        cancel_url=next_url(request) or "/todos/",
        submit_label=_("Save"),
    )
