"""The list by due date and the iCal feed (specs/todos.md, stage 2)"""

import datetime as dt

from django import forms
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from icalendar import Calendar, Event as CalendarEvent

from biwak import schedules
from biwak.accounts import sso
from biwak.accounts.languages import language_for
from biwak.accounts.models import CalendarToken, User
from biwak.activity import mentions
from biwak.api_conventions import absolute
from biwak.forms import Form
from biwak.items import due, glance
from biwak.organizations.names import display_name
from biwak.projects.models import Project
from biwak.projects.views import project_for


PAGE_SIZE = 50


class FilterForm(Form):
    """The filters, submitted with GET; invalid values show an error and no
    to-dos instead of being ignored"""

    project = forms.ModelChoiceField(
        label=_("project"),
        queryset=Project.objects.none(),
        required=False,
        empty_label=_("All projects"),
    )
    assignee = forms.ChoiceField(label=_("assigned to"), required=False)
    assigned_by = forms.ChoiceField(
        label=_("assigned by"),
        required=False,
        choices=[("", _("Anybody")), ("me", _("Me"))],
    )
    state = forms.ChoiceField(
        label=_("state"),
        required=False,
        choices=[("", _("Open")), ("completed", _("Completed"))],
    )
    visible = forms.ChoiceField(
        label=_("visibility"),
        required=False,
        choices=[
            ("", _("Everything")),
            ("yes", _("Visible to clients")),
            ("no", _("Internal")),
        ],
    )

    grouping = forms.ChoiceField(
        label=_("group by"),
        required=False,
        # The default is the empty choice, so it stays out of the URL
        choices=[("", _("Project")), ("due", _("Due date"))],
    )

    def __init__(self, data, *, user, project=None):
        super().__init__(data)
        projects = Project.objects.accessible_to(user).active()
        if project is not None:
            del self.fields["project"]
            projects = projects.filter(pk=project.pk)
        else:
            self.fields["project"].queryset = projects
        # The empty choice is the page's default (decided 2026-11-21)
        if default_assignee(project, data) == "me":
            choices = [("", _("Me")), (ANYBODY, _("Anybody"))]
        else:
            choices = [("", _("Anybody")), ("me", _("Me"))]
        choices.append(("nobody", _("Nobody active")))
        if not user.is_client:
            people = User.objects.filter(memberships__project__in=projects).distinct()
            choices += [
                (str(p.pk), display_name(p, user))
                for p in people.filter(is_active=True)
            ]
            # Inactive people after the active ones, so their open to-dos
            # can be listed and handed over (specs/handover.md)
            inactive = [
                (str(p.pk), display_name(p, user))
                for p in people.filter(is_active=False)
            ]
            if inactive:
                choices.append((_("Inactive"), inactive))
        self.fields["assignee"].choices = choices
        if user.is_client:
            del self.fields["visible"]


# The filters "Reset filters" resets
ANYBODY = "anybody"


def default_assignee(project, query):
    """What the empty "assigned to" means: across projects mine (everybody's
    can get huge), in a project anybody's, and anybody's for the to-dos I
    assigned too (else they'd be only those I gave myself; decided
    2026-11-22)"""
    if project is None and query.get("assigned_by") != "me":
        return "me"
    return ANYBODY


def without_empty(query):
    """``query`` (a ``QueryDict``) without empty values, which stay out of
    URLs (specs/ui.md)"""
    query = query.copy()
    for name, values in list(query.lists()):
        query.setlist(name, [value for value in values if value])
        if not query.getlist(name):
            del query[name]
    return query


FILTERS = ["project", "assignee", "assigned_by", "state", "visible"]


TodoGrouping = type("TodoGrouping", (), {"PROJECT": "project", "DUE": "due"})


def _title(data):
    """What the filters show: mine, the ones I assigned (to others too),
    or to-dos"""
    if data.get("assignee") == "me":
        return _("My to-dos")
    if data.get("assigned_by") == "me":
        return _("To-dos I assigned")
    return _("To-dos")


def todos_by_due(request, project=None):
    """Open to-dos by due date across the projects the person sees, or in
    one project; ``?assignee=me`` is "My to-dos". Rows are completed in
    place (``todo_toggle``)."""
    query = without_empty(request.GET)
    default = default_assignee(project, query)
    # Links spelling a default out (from before, or written by hand): the
    # default is the empty choice
    if query.get("assignee") == default:
        del query["assignee"]
    if query.get("grouping") == TodoGrouping.PROJECT:
        del query["grouping"]
    form = FilterForm(query, user=request.user, project=project)
    valid = form.is_valid()
    data = dict(form.cleaned_data) if valid else {}
    if valid:
        assignee = data["assignee"] or default
        data["assignee"] = "" if assignee == ANYBODY else assignee
    completed = data.get("state") == "completed"
    todos = due.todos(
        request.user,
        project=project or data.get("project"),
        assignee=data.get("assignee") or None,
        assigned_by=data.get("assigned_by") or None,
        completed=completed,
        visible_to_clients={"yes": True, "no": False}.get(data.get("visible")),
    )
    if not valid:
        todos = todos.none()
    todos = glance.with_signals(todos)
    grouping = data.get("grouping") or TodoGrouping.PROJECT
    # "Assigned to me" in the header: the same filters with me as the
    # assignee (specs/todos.md, "The to-dos page")
    mine = query.copy()
    mine.pop("page", None)
    mine.pop("assignee", None)
    if default != "me":
        mine["assignee"] = "me"
    context = {
        "mine_query": mine.urlencode(),
        "is_mine": data.get("assignee") == "me",
        # Reset only when a filter is set; the grouping is a view, not a filter
        "filtered": any(query.get(name) for name in FILTERS),
        "grouping": grouping,
        "form": form,
        "project": project,
        "completed": completed,
        "title": _title(data),
    }
    if completed:
        page = Paginator(
            todos.order_by("-todo__completed_at", "-pk"), PAGE_SIZE
        ).get_page(request.GET.get("page"))
        query = query.copy()
        query.pop("page", None)
        context |= {"page": page, "querystring": query.urlencode()}
    else:
        # Not yet started: collapsed at the end (specs/start-dates.md)
        today = schedules.today()
        context["later"] = list(due.starting_later(todos, today))
        todos = todos.filter(due.started(today))
        if grouping == TodoGrouping.PROJECT:
            context["projects"] = due.by_project(todos)
        else:
            context["sections"] = due.sections(due.ordered(todos), today)
    return render(request, "items/todos_by_due.html", context)


def project_todos(request, pk):
    return todos_by_due(request, project=project_for(request, pk))


# The iCal feed ----------------------------------------------------------


def calendar_for(user):
    """The person's open to-dos with a due date as all-day events, until the
    due date (from the start date if any); mentions
    as names the person may know, like the mails"""
    calendar = Calendar()
    calendar.add("prodid", "-//Biwak//To-dos//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "Biwak")
    qs = due.todos(user, assignee="me").filter(todo__due_on__isnull=False)
    with mentions.reading_as(user):
        for item in qs.order_by("todo__due_on", "pk"):
            event = CalendarEvent()
            event.add("uid", f"todo-{item.pk}@biwak")
            event.add("summary", mentions.title(item.title, item))
            # From the start date when there's one (specs/start-dates.md)
            event.add("dtstart", item.todo.starts_on or item.todo.due_on)
            event.add("dtend", item.todo.due_on + dt.timedelta(days=1))
            event.add("dtstamp", item.updated_at)
            event.add("transp", "TRANSPARENT")
            event.add("url", absolute(item.get_absolute_url()))
            todolist = mentions.plain(item.parent.title, item.parent)
            event.add("description", f"{item.project} / {todolist}")
            calendar.add_component(event)
    return calendar


@login_not_required
@never_cache
def calendar_feed(request, token):
    """No login: the secret in the URL is the key. It shows what the person
    sees now (nothing once they're inactive); an old link is a 404."""
    link = CalendarToken.objects.filter(token=token).select_related("user").first()
    if link is None or sso.requires_sso(link.user):
        # Not for organizations requiring single sign-on (specs/sso.md): a
        # link nobody signs in for would outlast leaving the company
        raise Http404
    # In its owner's language, not the calendar app's (specs/languages.md)
    with translation.override(language_for(link.user)):
        ical = calendar_for(link.user).to_ical()
    response = HttpResponse(ical, content_type="text/calendar; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    return response
