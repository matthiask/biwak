"""The activity feed, item history, notification settings, the @ list and
unsubscribing from mails (specs/feed.md, specs/notifications.md)"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import BadRequest, PermissionDenied
from django.db.models.functions import Lower
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
from biwak.activity.notify import (
    can_see,
    effective_level,
    item_level_context,
    level_choices,
)
from biwak.activity.operations import (
    NOTE_LENGTH,
    STAFF_ONLY,
    is_assigned,
    set_level_override,
    share,
    subscribable_people,
    unsubscribe as unsubscribe_from,
)
from biwak.forms import Form, PeopleField, PersonChoiceField, next_url
from biwak.items.models import Item, Kind
from biwak.items.views import item_for
from biwak.modals import form_response
from biwak.organizations.names import display_names
from biwak.projects.views import project_for
from biwak.teams.picking import mention_teams


class FilterForm(Form):
    """The feed's filters as query parameters"""

    kind = forms.ChoiceField(
        label=_("Kind"), choices=[("", _("All")), *Kind.choices], required=False
    )
    person = PersonChoiceField(
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
            # Nor do they see the staff's events (public links)
            self.fields["action"].choices = [
                choice
                for choice in self.fields["action"].choices
                if choice[0] not in STAFF_ONLY
            ]


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
            # How many: "Filters" on phones says it (specs/ui.md)
            "filtered": sum(
                1
                for name in ["kind", "person", "action", "clients"]
                if request.GET.get(name)
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
    return _with_teams(
        request,
        item.project,
        item.is_client_visible,
        mentions.candidates(item, request.GET.get("q", ""), for_user=request.user),
    )


def _with_teams(request, project, visible, people):
    """The teams after the people, for staff (specs/teams.md): choosing
    one mentions its members who can see it; only on the web, the API's
    list has people only"""
    teams = mention_teams(
        project,
        visible,
        request.GET.get("q", ""),
        for_user=request.user,
        names=display_names(request.user),
    )
    return JsonResponse(people + teams, safe=False)


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
    return _with_teams(
        request,
        project,
        visible,
        mentions.candidates_for(
            project, visible, request.GET.get("q", ""), for_user=request.user
        ),
    )


class SettingsForm(Form):
    notification_level = forms.ChoiceField(
        label=_("Notify me about"),
        choices=NotificationLevel.choices,
        widget=forms.RadioSelect,
        help_text=_(
            "What you're subscribed to automatically. Subscribed, you hear"
            " about everything on an item; unsubscribe to stop. Everything:"
            " posts to everybody subscribe you. Only what concerns me: being"
            " mentioned or assigned and your own things. Never about what you"
            " do yourself. The activity feed always shows everything."
        ),
    )
    mail_delivery = forms.ChoiceField(
        label=_("Mails"),
        choices=MailDelivery.choices,
        widget=forms.RadioSelect,
        help_text=_(
            "A mail about an item comes ten minutes after its last change;"
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


class LevelForm(Form):
    """A project's or an item's level, instead of the person's own"""

    level = forms.ChoiceField(
        label=_("Notify me about"), required=False, widget=forms.RadioSelect
    )

    def __init__(self, *args, default, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["level"].choices = level_choices(default)


@never_cache
def project_notifications(request, pk):
    """A project's override (the project page's "More" menu): a modal, also
    a page"""
    project = project_for(request, pk)
    if request.method == "POST":
        set_level_override(request.user, _level(request), project=project)
        messages.success(
            request, gettext("Your notification settings have been saved.")
        )
        return redirect(next_url(request) or project)
    override = LevelOverride.objects.filter(user=request.user, project=project).first()
    form = LevelForm(
        initial={"level": override.level if override else ""},
        default=request.user.notification_level,
    )
    return form_response(
        request,
        form,
        title=_("Notifications for this project"),
        intro=_(
            "Your own level for this project instead of the one in your"
            " settings: whether posts to everybody and new to-dos in lists"
            " you follow reach you. The activity feed always shows"
            " everything."
        ),
        project=project,
        cancel_url=project.get_absolute_url(),
    )


class SubscribersForm(Form):
    """Adding people to an item's subscribers (specs/subscribers.md): the
    people who can see the item and whom the person may know, the picker
    of the assignees; "Tell them now" with a note"""

    people = PeopleField(
        label=_("Add people"), queryset=User.objects.none(), required=True
    )
    notify = forms.BooleanField(
        label=_("Tell them now"),
        required=False,
        help_text=_("Otherwise they hear about the next change."),
    )
    note = forms.CharField(
        label=_("Note"),
        required=False,
        max_length=NOTE_LENGTH,
        help_text=_("One line, sent with “Tell them now”."),
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def __init__(self, *args, item, user, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["people"]
        # Those not subscribed yet; the first come first by name
        field.queryset = (
            subscribable_people(item, user)
            .exclude(subscriptions__item=item)
            .order_by(Lower("full_name"), "email")
        )
        field.error_messages["required"] = _("Pick at least one person.")
        # Teams add their members (specs/teams.md); the subscribers are in
        # already, and the person has their own button
        field.offer_teams(
            project=item.project,
            visible=item.is_client_visible,
            already=lambda: {
                user.pk,
                *item.subscriptions.values_list("user", flat=True),
            },
        )
        # The picker hides the select: the browser couldn't focus it to say
        # so, the server does
        field.widget.use_required_attribute = lambda initial: False
        field.widget.attrs |= {
            "data-placeholder": _("Add people…"),
            "aria-label": _("Add people"),
        }


@never_cache
def item_subscribers(request, pk):
    """Who gets mails about an item, and adding others ("Manage…" next to
    the subscribers): a modal, also a page. Everybody who sees the item may
    add people they may know; removing is each person's own business."""
    item = item_for(request, pk)
    form = SubscribersForm(
        request.POST or None,
        item=item,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        share(
            item,
            list(data["people"]),
            actor=request.user,
            notify=data["notify"],
            note=data["note"],
        )
        return redirect(next_url(request) or item)
    subscriptions = list(
        item.subscriptions.select_related("user", "added_by").order_by(
            Lower("user__full_name"), "user__email"
        )
    )
    # Clients and externals only learn about the members
    known = {
        user.pk
        for user in item.project.people_known_to(
            request.user,
            [s.user for s in subscriptions]
            + [s.added_by for s in subscriptions if s.added_by],
        )
    }
    return form_response(
        request,
        form,
        title=_("Subscribers"),
        intro=_("They get what happens to this, as their notification level says."),
        item=item,
        cancel_url=next_url(request) or item.get_absolute_url(),
        submit_label=_("Add"),
        template="activity/subscribers.html",
        extra={
            "subscriptions": [
                {
                    "user": s.user,
                    "added_by": s.added_by if s.added_by_id in known else None,
                }
                for s in subscriptions
                if s.user_id in known
            ],
        },
    )


@never_cache
def item_notifications(request, pk):
    """A list's override ("Notifications…" in its "More" menu): a modal,
    also a page; the settings page posts here too. Other items have no
    level (specs/notifications.md, "Subscriptions"): 404."""
    item = item_for(request, pk)
    if item.kind != Kind.LIST:
        raise Http404
    if request.method == "POST":
        set_level_override(request.user, _level(request), item=item)
        return redirect(next_url(request) or item)
    context = item_level_context(request.user, item)
    # The level it'd have without the override is the first choice's label
    form = LevelForm(
        initial={"level": context["level"]},
        default=effective_level(request.user, item.parent, project=item.project),
    )
    return form_response(
        request,
        form,
        title=_("Notifications for this list"),
        intro=_(
            "Your own level for this list instead of the one of the project:"
            " whether you hear about new to-dos in it. To-dos you're"
            " subscribed to tell you everything. The activity feed always"
            " shows everything."
        ),
        item=item,
        parent=item.parent,
        cancel_url=item.get_absolute_url(),
    )


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
    assigned = is_assigned(user, item)
    # Still assigned: the link does nothing and the page says why
    if request.method == "POST" and not assigned:
        unsubscribe_from(user, item)
        done = True
    title = ""
    # Only who may still see it learns the title, with the names the
    # mail's recipient may know (not who's logged in, if anybody)
    seen = can_see(user, item)
    if seen:
        with mentions.reading_as(user):
            title = mentions.title(item.title, item)
    return render(
        request,
        "activity/unsubscribe.html",
        {
            "done": done,
            "assigned": assigned,
            "title": title,
            "item": item,
            "can_open": seen,
        },
    )


# The lantern (specs/lantern.md) ----------------------------------------------


def _lantern_item(request):
    """The item posted (``item``), through ``item_for()``: 404 for what the
    person doesn't see"""
    return _lantern_items(request)[0]


def _lantern_items(request):
    """The items posted (``item``, several for a batch of files), through
    ``item_for()``: 404 for what the person doesn't see"""
    values = request.POST.getlist("item")
    if not values or not all(value.isdecimal() for value in values):
        raise Http404
    return [item_for(request, int(value)) for value in values]


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
    them: the entry stands for the item). The entries are links to where
    they apply, and frontend/lantern.js posts here in the background when
    one is followed (204); a plain post redirects there. Posting only, so
    another site can't read somebody's notifications by linking here
    (decided 2026-11-21); GET answers 405."""
    notification = lantern_module.notifications_for(request.user).filter(pk=pk).first()
    if notification is None:
        raise Http404
    # The entry stands for its item, or the files uploaded together
    lantern_module.read(
        request.user, items=lantern_module.entry_items(request.user, notification)
    )
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return redirect(lantern_module.anchor(notification))


@require_POST
def lantern_read(request):
    """Marks the notifications of an item (``item``) or all as read"""
    if request.POST.get("all"):
        lantern_module.read(request.user)
    else:
        lantern_module.read(request.user, items=_lantern_items(request))
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    return redirect(next_url(request) or "lantern")


@require_POST
def lantern_unread(request):
    """Marks an item's newest notification unread again (each file's of a
    batch)"""
    for item in _lantern_items(request):
        lantern_module.unread(request.user, item=item)
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
