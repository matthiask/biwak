"""What the to-dos page and a list's filters share (specs/todos.md)"""

from django import forms
from django.db.models import Exists, OuterRef
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User
from biwak.activity.mentions import known_to
from biwak.forms import Form
from biwak.items.models import Assignment, Status
from biwak.organizations.names import display_name


# The empty assignee's other meaning, spelled out
ANYBODY = "anybody"
# The to-dos outside groups (specs/todos.md, "Filters on a list")
NO_GROUP = "none"


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
    group = forms.ChoiceField(label=_("group"), required=False)

    def __init__(self, data, *, user, todolist):
        super().__init__(data)
        # One group, or the to-dos outside groups (decided 2026-11-26 by
        # the user); only in lists with groups
        if groups := list(todolist.todolist.groups.all()):
            self.fields["group"].choices = [
                ("", _("All groups")),
                (NO_GROUP, _("No group")),
                *((str(g.pk), g.title) for g in groups),
            ]
        else:
            del self.fields["group"]
        # Only people with to-dos in the list, open or completed (both are
        # filtered; decided 2026-11-24 by the user), whom the person may know:
        # people removed from the project stay on completed to-dos, and
        # externals don't learn their names (specs/access.md)
        assigned = Assignment.objects.filter(
            user=OuterRef("pk"), todo__item__parent=todolist
        ).exclude(todo__item__status=Status.TRASHED)
        people = known_to(User.objects.filter(Exists(assigned)), todolist.project, user)
        self.fields["assignee"].choices = assignee_choices(user, people)

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


def in_group(todos, group):
    """The to-dos of ``todos`` in the group with the ID ``group`` (a string
    or an int), or outside groups (``NO_GROUP``); ``None``: all"""
    if not group:
        return todos
    if group == NO_GROUP:
        return todos.filter(todo__group=None)
    return todos.filter(todo__group_id=int(group))
