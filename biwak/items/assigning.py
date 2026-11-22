"""Assigning several to-dos at once: the selection's "Assign…" on the to-dos
page and a list's page (specs/handover.md)"""

from django import forms
from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _, ngettext

from biwak.accounts.models import User
from biwak.forms import Form, PeopleField, next_url
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
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


def todos_assign(request):
    """ "Assign…" for the selected to-dos (``items``, in the query): a modal,
    also a page. All or nothing: to-dos the person can't change (gone
    meanwhile) or somebody who can't be assigned to one of them change
    nothing, the form says how many and why."""
    ids = ids_of(request.GET.getlist("items"))
    todos, missing = todos_for(request.user, ids)
    if not todos:
        raise Http404
    form = AssignForm(
        request.POST if request.method == "POST" else None,
        todos=todos,
        user=request.user,
    )
    if missing:
        # Said before posting too: nothing would change
        form.is_valid()
        if not form.is_bound:
            form.cleaned_data = {}
        form.add_error(None, missing_message(missing))
    elif form.is_valid():
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
        intro=ngettext("“%(title)s”", "%(count)s to-dos", len(todos))
        % {"title": todos[0].title, "count": len(todos)},
        project=todos[0].project if len({t.project_id for t in todos}) == 1 else None,
        cancel_url=next_url(request) or "/todos/",
        submit_label=_("Assign"),
    )
