"""Copying a list and moving top-level items to another project: the
modals (specs/lists-across-projects.md)

Both ask before doing what can't be seen in the form: who is left out
(assignees and subscribers who aren't members of the target project) and
who would see it (clients of the target). The form comes back with these
sentences and ``confirmed`` set to what they're about; posting it again
with the same target does it.
"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import redirect
from django.utils.text import get_text_list
from django.utils.translation import gettext, gettext_lazy as _, ngettext

from biwak.forms import ComboboxSelect, Form, next_url
from biwak.items import operations as ops
from biwak.items.models import Kind
from biwak.items.views import item_for, show_texts
from biwak.modals import form_response
from biwak.projects.models import Project


NO_NOTES = ("", "")


def target_projects(user, item):
    """The projects the person may move the top-level ``item`` to: those
    they open, not archived, where they may create such items, not its
    own. None for items in a folder (they move with it, or to the top
    first)."""
    if (
        item.kind not in ops.MOVABLE
        or item.parent_id is not None
        or item.project.archived_at is not None
        or not ops.can_create(user, item.kind)
    ):
        return Project.objects.none()
    return (
        Project.objects
        .accessible_to(user)
        .filter(archived_at__isnull=True)
        .exclude(pk=item.project_id)
        .order_by(Lower("name"), "pk")
    )


def _names(people, project, viewer):
    """The names of ``people`` the viewer may know in ``project``, the
    others counted"""
    known = project.people_known_to(viewer, people)
    names = [str(user) for user in known]
    if others := len(people) - len(known):
        names.append(
            ngettext("%(count)d other person", "%(count)d other people", others)
            % {"count": others}
        )
    return get_text_list(names, gettext("and"))


def move_notes(item, project, viewer):
    """What moving the item to ``project`` does that the form doesn't
    show: who is dropped, and the clients who'd see it (asking like "Show
    to clients…"): ``(who's dropped, who'd see it)``, each a sentence or
    empty."""
    note = clients_note = ""
    dropped = list(ops.move_dropped(item, project))
    if dropped:
        note = ngettext(
            "%(names)s isn't in %(project)s: they'll be unassigned and unsubscribed.",
            "%(names)s aren't in %(project)s: they'll be unassigned and unsubscribed.",
            len(dropped),
        ) % {"names": _names(dropped, item.project, viewer), "project": project}
    if clients := ops.new_clients(item, project).count():
        clients_note = show_texts(item, clients)[1]
    return note, clients_note


def copy_notes(item, project, visible, viewer):
    """What copying the list to ``project`` leaves out, and the clients who'd
    see the copy: ``(who's left out, who'd see it)``"""
    note = clients_note = ""
    dropped = list(ops.copy_dropped(item, project))
    if dropped:
        note = ngettext(
            "%(names)s isn't in %(project)s: left unassigned.",
            "%(names)s aren't in %(project)s: left unassigned.",
            len(dropped),
        ) % {"names": _names(dropped, item.project, viewer), "project": project}
    clients = 0
    if visible:
        clients = (
            project.memberships
            .filter(user__is_client=True, user__is_active=True)
            .values("user")
            .distinct()
            .count()
        )
    if clients:
        todos = ops.open_todos(item).count()
        clients_note = _("Makes the copy and %(todos)s visible to %(clients)s.") % {
            "todos": ngettext("%(count)d to-do", "%(count)d to-dos", todos)
            % {"count": todos},
            "clients": ngettext("%(count)d client", "%(count)d clients", clients)
            % {"count": clients},
        }
    return note, clients_note


class ProjectChoice(forms.ModelChoiceField):
    def __init__(self, queryset, **kwargs):
        super().__init__(queryset, widget=ComboboxSelect(), **kwargs)


class Confirming(Form):
    """``confirmed``: what the sentences shown were about"""

    confirmed = forms.CharField(widget=forms.HiddenInput, required=False)

    def asked(self, key):
        """Whether the person saw the sentences about ``key``; if not,
        the form shown again asks"""
        if self.cleaned_data.get("confirmed") == key:
            return True
        data = self.data.copy()
        data["confirmed"] = key
        self.data = data
        return False


class MoveForm(Confirming):
    project = ProjectChoice(Project.objects.none(), label=_("project"))

    def __init__(self, *args, projects, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects


def asking(request, form, *, title, item, notes, submit_label, cancel_url):
    """The form, and what it does that the form doesn't show (``notes``,
    from ``move_notes()`` or ``copy_notes()``)"""
    note, clients_note = notes
    return form_response(
        request,
        form,
        title=title,
        item=item,
        cancel_url=cancel_url,
        submit_label=submit_label,
        destructive=bool(clients_note),
        template="items/across_form.html",
        extra={"note": note, "clients_note": clients_note},
    )


def confirmed_move(request, item, project, form):
    """Moves the item to ``project`` once the person saw what it does
    (``form.asked()``); else None, and the form asks: ``(response,
    notes)``"""
    notes = move_notes(item, project, request.user)
    if any(notes) and not form.asked(str(project.pk)):
        return None, notes
    try:
        ops.move_to_project(item, project=project, actor=request.user)
    except ValueError as exc:
        form.add_error(None, str(exc))
        return None, NO_NOTES
    return redirect(item), NO_NOTES


def item_move_project(request, pk):
    """ "Move to…" of lists and messages: another project (a modal, also a
    page); folders, docs and files have theirs (``files.library.item_move``)
    with the folders too"""
    item = item_for(request, pk)
    if item.kind not in {Kind.LIST, Kind.MESSAGE}:
        raise Http404
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = MoveForm(request.POST or None, projects=target_projects(request.user, item))
    notes = NO_NOTES
    if form.is_valid():
        response, notes = confirmed_move(
            request, item, form.cleaned_data["project"], form
        )
        if response is not None:
            return response
    return asking(
        request,
        form,
        title=_("Move to…"),
        item=item,
        notes=notes,
        submit_label=_("Move"),
        cancel_url=next_url(request) or item.get_absolute_url(),
    )


class CopyForm(Confirming):
    project = ProjectChoice(Project.objects.none(), label=_("project"))
    title = forms.CharField(
        label=_("title"),
        max_length=500,
        help_text=_("Gets “(copy)” if the project has a list of that name."),
    )
    dates = forms.ChoiceField(
        label=_("Due dates"),
        choices=ops.Dates.choices,
        initial=ops.Dates.KEEP,
        widget=forms.RadioSelect,
    )
    days = forms.IntegerField(
        label=_("Days"),
        required=False,
        min_value=-3650,
        max_value=3650,
        help_text=_("For “Move by”: negative numbers move them earlier."),
    )
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)

    def __init__(self, *args, projects, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects

    def clean(self):
        data = super().clean()
        if data.get("dates") == ops.Dates.SHIFT and not data.get("days"):
            self.add_error("days", _("By how many days?"))
        return data


def copy_targets(user):
    """The projects the person may copy a list to: those they open and
    create lists in, not archived"""
    if not ops.can_create(user, Kind.LIST):
        return Project.objects.none()
    return (
        Project.objects
        .accessible_to(user)
        .filter(archived_at__isnull=True)
        .order_by(Lower("name"), "pk")
    )


def list_copy(request, pk):
    """ "Copy…" of a list (a modal, also a page): into a project, with a
    title and what happens to the due dates; staff only, like creating
    lists"""
    item = item_for(request, pk, Kind.LIST)
    if not ops.can_create(request.user, Kind.LIST):
        raise PermissionDenied
    projects = copy_targets(request.user)
    form = CopyForm(
        request.POST or None,
        projects=projects,
        initial={
            "project": item.project if item.project.archived_at is None else None,
            "title": item.title,
        },
    )
    notes = NO_NOTES
    if form.is_valid():
        data = form.cleaned_data
        project, visible = data["project"], data["visible"]
        notes = copy_notes(item, project, visible, request.user)
        if not any(notes) or form.asked(f"{project.pk}:{int(visible)}"):
            try:
                copy = ops.copy_list(
                    item,
                    project=project,
                    title=data["title"],
                    actor=request.user,
                    dates=data["dates"],
                    days=data["days"] or 0,
                    visible=visible,
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
                notes = NO_NOTES
            else:
                return redirect(copy)
    return asking(
        request,
        form,
        title=_("Copy…"),
        item=item,
        notes=notes,
        submit_label=_("Copy"),
        cancel_url=item.get_absolute_url(),
    )
