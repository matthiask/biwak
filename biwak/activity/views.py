"""The activity feed, item history, notification settings, the @ list and
unsubscribing from mails (specs/feed.md, specs/notifications.md)"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import BadRequest, PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from biwak.accounts.models import MailDelivery, NotificationLevel, User
from biwak.activity import (
    feed as feed_module,
    history,
    lantern as lantern_module,
    mentions,
)
from biwak.activity.mails import read_unsubscribe_token
from biwak.activity.models import Action, LevelOverride
from biwak.activity.notify import can_see, level_choices
from biwak.activity.operations import (
    set_level_override,
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
        found, more = feed_module.page(
            events, request.GET.get("before"), user=request.user
        )
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
        if not folder_id.isdecimal():
            raise Http404
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
            " the digest at 07:00 with what happened the day before. What"
            " you read in the lantern before isn't mailed."
        ),
    )
    lantern_in_favicon = forms.BooleanField(
        label=_("A dot on the tab's icon while there are unread notifications"),
        required=False,
    )


def _level(request):
    """The level posted, None for the person's default"""
    level = request.POST.get("level") or None
    if level is not None and level not in NotificationLevel.values:
        raise BadRequest("Invalid level.")
    return level


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
    title = ""
    # Only who may still see it learns the title, with the names the
    # mail's recipient may know (not who's logged in, if anybody)
    if can_see(user, item):
        with mentions.reading_as(user):
            title = mentions.plain(item.title, item)
    return render(
        request,
        "activity/unsubscribe.html",
        {
            "done": done,
            "title": title,
            "item": item,
        },
    )


# The lantern (specs/lantern.md) ----------------------------------------------


def _lantern_item(request):
    """The item posted (``item``), through ``item_for()``: 404 for what the
    person doesn't see"""
    value = request.POST.get("item", "")
    if not value.isdecimal():
        raise Http404
    return item_for(request, int(value))


@never_cache
def lantern(request):
    """The lantern's page: everything, newest first, grouped by item; the
    filters "unread" and "mentions only"; pages like the feed"""
    unread = bool(request.GET.get("unread"))
    mentioned = bool(request.GET.get("mentions"))
    try:
        groups, cursor = lantern_module.page(
            request.user,
            unread=True if unread else None,
            mentions=mentioned,
            before=request.GET.get("before"),
        )
    except ValueError:
        return HttpResponseBadRequest("Invalid cursor.")
    query = request.GET.copy()
    query.pop("before", None)
    older = None
    if cursor:
        query["before"] = cursor
        older = f"{reverse('lantern')}?{query.urlencode()}"
    return render(
        request,
        "activity/lantern.html",
        {
            "bookmarked_groups": []
            if request.GET.get("before")
            else lantern_module.bookmarked(request.user),
            "groups": groups,
            "older": older,
            "unread": unread,
            "mentions": mentioned,
            "filtered": unread or mentioned,
        },
    )


@never_cache
def lantern_menu(request):
    """The menu's content (frontend/lantern.js fetches it when opened)"""
    bookmarked, unread, read, more = lantern_module.menu(request.user)
    return render(
        request,
        "activity/_lantern_menu.html",
        {
            "bookmarked_groups": bookmarked,
            "unread_groups": unread,
            "read_groups": read,
            "more_unread": more,
        },
    )


@never_cache
def lantern_count(request):
    """The number of unread notifications, for the menu's button"""
    return JsonResponse({"unread": lantern_module.unread_count(request.user)})


@require_POST
def lantern_open(request, pk):
    """Following an entry: reads the notifications of its item (all of
    them: the entry stands for the item) and opens the item where the
    notification applies. A form posting, so that it works without
    JavaScript and another site can't read somebody's notifications by
    linking here (decided 2026-11-21); GET answers 405."""
    notification = lantern_module.notifications_for(request.user).filter(pk=pk).first()
    if notification is None:
        raise Http404
    lantern_module.read(request.user, item=notification.event.item)
    return redirect(lantern_module.anchor(notification))


@require_POST
def lantern_read(request):
    """Marks the notifications of an item (``item``) or all as read"""
    if request.POST.get("all"):
        lantern_module.read(request.user)
    else:
        lantern_module.read(request.user, item=_lantern_item(request))
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return redirect(next_url(request) or "lantern")


@require_POST
def lantern_unread(request):
    """Marks an item's newest notification unread again"""
    lantern_module.unread(request.user, item=_lantern_item(request))
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return redirect(next_url(request) or "lantern")


@require_POST
def lantern_bookmark(request):
    """Bookmarks an item, its notifications at the top, or removes the
    bookmark (``remove``)"""
    item = _lantern_item(request)
    if request.POST.get("remove"):
        lantern_module.unbookmark(request.user, item)
    else:
        lantern_module.bookmark(request.user, item)
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return redirect(next_url(request) or "lantern")
