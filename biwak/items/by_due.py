"""The list by due date and the iCal feed (specs/todos.md, stage 2)"""

import datetime as dt

from django import forms
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from icalendar import Calendar, Event as CalendarEvent

from biwak import schedules
from biwak.accounts.models import CalendarToken, User
from biwak.activity import mentions
from biwak.api_conventions import absolute
from biwak.forms import Form, next_url
from biwak.items import due, glance, operations as ops
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
        completed=completed,
        visible_to_clients={"yes": True, "no": False}.get(data.get("visible")),
    )
    if not valid:
        todos = todos.none()
    todos = glance.with_signals(todos)
    grouping = request.GET.get("grouping")
    if grouping in User.TodoGrouping.values:
        # The links of the switch without JavaScript store it too
        ops.set_todo_grouping(request.user, grouping)
    grouping = request.user.todo_grouping
    context = {
        "grouping": grouping,
        "groupings": User.TodoGrouping.choices,
        "form": form,
        "project": project,
        "completed": completed,
        "title": _("My to-dos") if request.GET.get("assignee") == "me" else _("To-dos"),
    }
    if completed:
        page = Paginator(
            todos.order_by("-todo__completed_at", "-pk"), PAGE_SIZE
        ).get_page(request.GET.get("page"))
        query = request.GET.copy()
        query.pop("page", None)
        context |= {"page": page, "querystring": query.urlencode()}
    elif grouping == User.TodoGrouping.PROJECT:
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


@require_POST
def todo_grouping(request):
    """The switch on the to-dos page, remembered per person; comes back to
    the page with its filters"""
    try:
        ops.set_todo_grouping(request.user, request.POST.get("grouping"))
    except ValueError:
        return HttpResponse(status=400)
    return redirect(next_url(request) or "todos")


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
