from django import forms
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from biwak.accounts.models import User
from biwak.activity import feed as feed_module
from biwak.activity.models import Action
from biwak.forms import Form
from biwak.items.models import Kind
from biwak.projects.views import project_for


class FilterForm(Form):
    """The feed's filters as query parameters"""

    kind = forms.ChoiceField(
        label=_("Kind"), choices=[("", _("All")), *Kind.choices], required=False
    )
    person = forms.ModelChoiceField(
        label=_("Person"),
        queryset=User.objects.none(),
        required=False,
        empty_label=_("Everybody"),
    )
    action = forms.ChoiceField(
        label=_("Action"), choices=[("", _("All")), *Action.choices], required=False
    )
    clients = forms.BooleanField(label=_("Visible to clients"), required=False)

    def __init__(self, *args, user, project=None, with_person=True, **kwargs):
        super().__init__(*args, **kwargs)
        if with_person:
            self.fields["person"].queryset = feed_module.people_visible_to(
                user, project
            )
        else:
            del self.fields["person"]
        if user.is_client:
            # Everything a client sees is visible to clients
            del self.fields["clients"]


def feed_page(request, *, title, url, project=None, person=None):
    form = FilterForm(
        request.GET or None,
        user=request.user,
        project=project,
        with_person=person is None,
    )
    filters = form.cleaned_data if form.is_valid() else {}
    if person is not None:
        filters["person"] = person
    # Invalid filter values are ignored, the form shows the errors
    events = feed_module.feed_events(
        request.user,
        project=project,
        person=filters.get("person"),
        kind=filters.get("kind"),
        action=filters.get("action"),
        visible_to_clients=filters.get("clients", False),
    )
    try:
        found, more = feed_module.page(events, request.GET.get("before"))
    except ValueError:
        return HttpResponseBadRequest("Invalid cursor.")
    today = timezone.localdate()
    days = [
        (day, feed_module.day_label(day, today), entries)
        for day, entries in feed_module.by_day(feed_module.merge(found))
    ]
    query = request.GET.copy()
    query.pop("before", None)
    older = None
    if more:
        query["before"] = more
        older = f"{url}?{query.urlencode()}"
    return render(
        request,
        "activity/feed.html",
        {
            "title": title,
            "url": url,
            "project": project,
            "person": person,
            "form": form,
            "days": days,
            "older": older,
            "filtered": any(
                request.GET.get(name)
                for name in ["kind", "person", "action", "clients"]
            ),
        },
    )


def feed(request):
    return feed_page(request, title=gettext("Activity"), url=reverse("feed"))


def project_feed(request, pk):
    project = project_for(request, pk)
    return feed_page(
        request,
        title=gettext("Activity in %(project)s") % {"project": project},
        url=reverse("project_feed", args=[project.pk]),
        project=project,
    )


def person_feed(request, pk):
    person = get_object_or_404(feed_module.people_visible_to(request.user), pk=pk)
    return feed_page(
        request,
        title=gettext("Activity of %(person)s") % {"person": person.display_name},
        url=reverse("person_feed", args=[person.pk]),
        person=person,
    )
