"""What the to-dos page and a list's filters share (specs/todos.md)"""

from django import forms
from django.db.models import Exists, OuterRef
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User
from biwak.forms import Form
from biwak.items.models import Assignment, Status
from biwak.organizations.names import display_name


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


def assignee_choices(user, people, *, mine=False):
    """The choices of "assigned to", the empty one the default (decided
    2026-11-21): "Me" with ``mine``, else "Anybody"; ``people`` (a
    queryset of users) only for staff"""
    if mine:
        choices = [("", _("Me")), (ANYBODY, _("Anybody"))]
    else:
        choices = [("", _("Anybody")), ("me", _("Me"))]
    choices.append(("nobody", _("Nobody active")))
    if not user.is_client:
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

    def __init__(self, data, *, user, todolist):
        super().__init__(data)
        # Only people with to-dos in the list, open or completed (both are
        # filtered; decided 2026-11-24 by the user)
        assigned = Assignment.objects.filter(
            user=OuterRef("pk"), todo__item__parent=todolist
        ).exclude(todo__item__status=Status.TRASHED)
        self.fields["assignee"].choices = assignee_choices(
            user, User.objects.filter(Exists(assigned))
        )

    def chosen(self):
        """The filters set, as (label, the choice's label), for the line
        saying the list is filtered"""
        result = []
        for name, field in self.fields.items():
            if value := self.cleaned_data.get(name):
                labels = {}
                for key, label in field.choices:
                    labels |= (
                        dict(label) if isinstance(label, list | tuple) else {key: label}
                    )
                result.append((field.label, labels[value]))
        return result
