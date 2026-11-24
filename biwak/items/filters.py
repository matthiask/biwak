"""What the to-dos page and a list's filters share (specs/todos.md)"""

from django import forms
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User
from biwak.forms import Form
from biwak.organizations.names import display_name
from biwak.projects.models import Project


# The empty assignee's other meaning, spelled out
ANYBODY = "anybody"


def without_empty(query):
    """``query`` (a ``QueryDict``) without empty values, which stay out of
    URLs (specs/ui.md)"""
    query = query.copy()
    for name, values in list(query.lists()):
        query.setlist(name, [value for value in values if value])
        if not query.getlist(name):
            del query[name]
    return query


def assignee_choices(user, projects, *, mine=False):
    """The choices of "assigned to", the empty one the default (decided
    2026-11-21): "Me" with ``mine``, else "Anybody"; people of
    ``projects`` only for staff"""
    if mine:
        choices = [("", _("Me")), (ANYBODY, _("Anybody"))]
    else:
        choices = [("", _("Anybody")), ("me", _("Me"))]
    choices.append(("nobody", _("Nobody active")))
    if not user.is_client:
        people = User.objects.filter(memberships__project__in=projects).distinct()
        choices += [
            (str(p.pk), display_name(p, user)) for p in people.filter(is_active=True)
        ]
        # Inactive people after the active ones, so their open to-dos
        # can be listed and handed over (specs/handover.md)
        inactive = [
            (str(p.pk), display_name(p, user)) for p in people.filter(is_active=False)
        ]
        if inactive:
            choices.append((_("Inactive"), inactive))
    return choices


class ListFilterForm(Form):
    """A list's and its board's filter (specs/todos.md, "Filters on a
    list"), anybody's to-dos by default as on a project's to-dos page"""

    assignee = forms.ChoiceField(label=_("assigned to"), required=False)

    def __init__(self, data, *, user, project):
        super().__init__(data)
        self.fields["assignee"].choices = assignee_choices(
            user, Project.objects.filter(pk=project.pk)
        )
