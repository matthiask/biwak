"""The list by due date and the iCal feed (specs/todos.md, stage 2)"""

import datetime as dt

from django import forms
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from icalendar import Calendar, Event as CalendarEvent

from biwak import schedules
from biwak.accounts.models import CalendarToken, User
from biwak.activity import mentions
from biwak.api_conventions import absolute
from biwak.forms import Form
from biwak.items import due, glance
from biwak.organizations.names import display_name
from biwak.projects.models import Project
from biwak.projects.views import project_for


GROUP_LABELS = {
    due.OVERDUE: _("Overdue"),
    due.TODAY: _("Today"),
    due.THIS_WEEK: _("This week"),
    due.LATER: _("Later"),
    due.NO_DATE: _("No date"),
}
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
        choices=[("project", _("Project")), ("due", _("Due date"))],
    )

    def __init__(self, data, *, user, project=None):
        super().__init__(data)
        projects = Project.objects.accessible_to(user).active()
        if project is not None:
            del self.fields["project"]
            projects = projects.filter(pk=project.pk)
        else:
            self.fields["project"].queryset = projects
        choices = [("", _("Anybody")), ("me", _("Me")), ("nobody", _("Nobody"))]
        if not user.is_client:
            people = User.objects.active().filter(memberships__project__in=projects)
            choices += [(str(p.pk), display_name(p, user)) for p in people.distinct()]
        self.fields["assignee"].choices = choices
        if user.is_client:
            del self.fields["visible"]


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
    form = FilterForm(request.GET, user=request.user, project=project)
    valid = form.is_valid()
    data = form.cleaned_data if valid else {}
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
    context = {
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
        query = request.GET.copy()
        query.pop("page", None)
        context |= {"page": page, "querystring": query.urlencode()}
    elif grouping == TodoGrouping.PROJECT:
        context["projects"] = due.by_project(todos)
    else:
        today = schedules.today()
        sections = {key: [] for key in due.GROUPS}
        for item in due.ordered(todos):
            sections[due.group_of(item.todo.due_on, today)].append(item)
        context["sections"] = [
            (key, GROUP_LABELS[key], items) for key, items in sections.items() if items
        ]
    return render(request, "items/todos_by_due.html", context)


def project_todos(request, pk):
    return todos_by_due(request, project=project_for(request, pk))


# The iCal feed ----------------------------------------------------------


def calendar_for(user):
    """The person's open to-dos with a due date as all-day events; mentions
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
            event.add("summary", mentions.plain(item.title, item))
            event.add("dtstart", item.todo.due_on)
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
    if link is None:
        raise Http404
    response = HttpResponse(
        calendar_for(link.user).to_ical(), content_type="text/calendar; charset=utf-8"
    )
    response["Cache-Control"] = "private, no-store"
    return response
