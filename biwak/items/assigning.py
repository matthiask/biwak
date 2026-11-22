"""Changing several to-dos at once: the selection's "Assign…", "Move…" and
"Due date…" on the to-dos page and a list's page (specs/handover.md)"""

from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _, ngettext

from biwak.accounts.models import User
from biwak.forms import Form, PeopleField, next_url
from biwak.items import operations as ops
from biwak.items.models import Group, Item, Kind
from biwak.items.views import MoveTodoForm, _index, _move_targets, item_for
from biwak.modals import form_response


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
        .select_related("project", "todo")
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


def todos_move(request):
    """ "Move…" for the selected to-dos: a list of their project or a group
    of it, and where in it, like a to-do's "Move to…" (``move_todos()``,
    next to each other in their order). All or nothing, like "Assign…"."""
    todos, missing = _selected(request)
    project = _project(todos)
    form = MoveTodoForm(
        request.POST if request.method == "POST" else None,
        targets=_move_targets(request, todos[0]) if project else [],
    )
    if _refuse_missing(form, missing):
        pass
    elif project is None:
        _refuse(form, several_projects_message())
    elif form.is_valid():
        list_id, _sep, group_id = form.cleaned_data["target"].partition(":")
        target = item_for(request, int(list_id), Kind.LIST)
        group = None
        if group_id:
            group = get_object_or_404(Group, pk=int(group_id), todolist=target.todolist)
        ops.move_todos(
            todos,
            todolist=target,
            group=group,
            index=_index(form.cleaned_data["index"]),
            actor=request.user,
        )
        return redirect(next_url(request) or "todos")
    return form_response(
        request,
        form,
        title=_("Move…"),
        intro=_intro(todos),
        project=project,
        cancel_url=next_url(request) or "/todos/",
        submit_label=_("Move"),
    )


def several_projects_message():
    return _(
        "The selected to-dos are in several projects: to-dos move to the"
        " lists of their own project."
    )


class DatesForm(Form):
    """What "Due date…" does: the choices of copying a list, "Keep" being
    one date for all here"""

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
