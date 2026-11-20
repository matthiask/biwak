"""The activity feed, item history, notification settings, the @ list and
unsubscribing from mails (specs/feed.md, specs/notifications.md)"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from biwak.accounts.models import MailDelivery, NotificationLevel, User
from biwak.activity import feed as feed_module, history, mentions
from biwak.activity.mails import read_unsubscribe_token
from biwak.activity.models import Action, LevelOverride
from biwak.activity.notify import can_see, effective_level
from biwak.activity.operations import (
    set_level_override,
    set_notification_settings,
    unsubscribe as unsubscribe_from,
)
from biwak.forms import Form, next_url
from biwak.items.models import Item, Kind
from biwak.items.views import item_for
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


def item_history(request, pk):
    """The changes of an item from the audit log. Staff only: old versions
    of texts can hold what was meant to be internal, also on items clients
    see now."""
    item = item_for(request, pk)
    if request.user.is_client:
        raise PermissionDenied
    return render(
        request,
        "activity/history.html",
        {"item": item, "changes": history.history(item, request.user)},
    )


def mentionable(request, pk, kind=None):
    """The @ list (frontend/mentions.js): ``?q=``, at most 10 people, those
    who can't see the item greyed out with the reason"""
    item = item_for(request, pk, kind)
    return JsonResponse(
        mentions.candidates(item, request.GET.get("q", ""), for_user=request.user),
        safe=False,
    )


def mentionable_list(request, pk):
    """For to-dos not created yet: who can see the list"""
    return mentionable(request, pk, Kind.LIST)


def mentionable_new(request, pk):
    """For messages, docs and files not created yet: the people who will see
    them. ``?visible=1`` for visible to clients, ``?folder=`` for the folder
    of a doc or file (it decides, like when saving); clients always create
    what clients see."""
    project = project_for(request, pk)
    visible = request.user.is_client or bool(request.GET.get("visible"))
    if folder_id := request.GET.get("folder"):
        folder = item_for(request, folder_id, Kind.FOLDER)
        if folder.project_id != project.pk:
            raise Http404
        visible = folder.is_client_visible
    return JsonResponse(
        mentions.candidates_for(
            project, visible, request.GET.get("q", ""), for_user=request.user
        ),
        safe=False,
    )


class SettingsForm(Form):
    notification_level = forms.ChoiceField(
        label=_("Notify me about"),
        choices=NotificationLevel.choices,
        widget=forms.RadioSelect,
        help_text=_(
            "Never about what you do yourself. Being mentioned gets through"
            " unless you choose nothing. The activity feed always shows"
            " everything."
        ),
    )
    mail_delivery = forms.ChoiceField(
        label=_("Mails"),
        choices=MailDelivery.choices,
        widget=forms.RadioSelect,
        help_text=_(
            "A mail about an item comes two minutes after its last change;"
            " the digest at 07:00 with what happened the day before."
        ),
    )


@never_cache
def notification_settings(request):
    form = SettingsForm(
        request.POST or None,
        initial={
            "notification_level": request.user.notification_level,
            "mail_delivery": request.user.mail_delivery,
        },
    )
    if form.is_valid():
        set_notification_settings(
            request.user,
            level=form.cleaned_data["notification_level"],
            delivery=form.cleaned_data["mail_delivery"],
        )
        messages.success(
            request, gettext("Your notification settings have been saved.")
        )
        return redirect("notification_settings")
    overrides = LevelOverride.objects.filter(user=request.user).select_related(
        "project", "item"
    )
    visible = set(
        Item.objects
        .visible_to(request.user)
        .filter(pk__in=[o.item_id for o in overrides if o.item_id])
        .values_list("pk", flat=True)
    )
    return render(
        request,
        "activity/notification_settings.html",
        {
            "form": form,
            "project_overrides": [o for o in overrides if o.project_id],
            "item_overrides": [o for o in overrides if o.item_id in visible],
        },
    )


def _level(request):
    """The level posted, None for the person's default"""
    level = request.POST.get("level") or None
    if level is not None and level not in NotificationLevel.values:
        raise Http404
    return level


def level_choices(default):
    return [
        (
            "",
            gettext("As usual (%(level)s)")
            % {"level": NotificationLevel(default).label},
        ),
        *NotificationLevel.choices,
    ]


@never_cache
def project_notifications(request, pk):
    """A project's override (the project page's "More" menu)"""
    project = project_for(request, pk)
    if request.method == "POST":
        set_level_override(request.user, _level(request), project=project)
        messages.success(
            request, gettext("Your notification settings have been saved.")
        )
        return redirect(next_url(request) or project)
    override = LevelOverride.objects.filter(user=request.user, project=project).first()
    return render(
        request,
        "activity/project_notifications.html",
        {
            "project": project,
            "current": override.level if override else "",
            "choices": level_choices(request.user.notification_level),
        },
    )


@require_POST
def item_notifications(request, pk):
    """An item's override (next to its subscribe button)"""
    item = item_for(request, pk)
    set_level_override(request.user, _level(request), item=item)
    return redirect(next_url(request) or item)


def item_level_context(user, item):
    """For the form next to the subscribe button"""
    override = LevelOverride.objects.filter(user=user, item=item).first()
    default = effective_level(user, item.parent, project=item.project)
    return {
        "level": override.level if override else "",
        "level_choices": level_choices(default),
    }


@login_not_required
@csrf_exempt
@never_cache
def unsubscribe(request, token):
    """From a mail, without logging in (RFC 8058: mail programs POST
    ``List-Unsubscribe=One-Click``). A GET only asks, link checkers
    follow links."""
    if not (ids := read_unsubscribe_token(token)):
        raise Http404
    user = User.objects.active().filter(pk=ids[0]).first()
    item = Item.objects.filter(pk=ids[1]).select_related("project").first()
    if user is None or item is None:
        raise Http404
    done = False
    if request.method == "POST":
        unsubscribe_from(user, item)
        done = True
    return render(
        request,
        "activity/unsubscribe.html",
        {
            "done": done,
            # Only who may still see it learns the title
            "title": mentions.plain(item.title, item) if can_see(user, item) else "",
            "item": item,
        },
    )
