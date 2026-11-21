"""What the pages of messages, docs and files share"""

from django import forms
from django.db.models.functions import Lower
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User
from biwak.activity.notify import everybody
from biwak.activity.operations import is_assigned, is_subscribed
from biwak.forms import Form, PeopleField, PeopleSelect
from biwak.items import operations as ops
from biwak.items.views import CommentForm


class NotifyForm(Form):
    """ "Whom to notify" when posting (``notify_people()``,
    specs/notifications.md): everybody in the project, chosen people or
    nobody. Everybody is preselected (decided 2026-11-20): it subscribes
    only those notified by default, not those who want to hear only when
    tagged (specs/notifications.md, "Subscriptions"). "These people" is the people
    picker, shown only with "Only these people" (``shown_when``,
    ``frontend/shown-when.js``), with those "Everybody" would reach
    preselected (``notify.everybody()``), never the poster (decided
    2026-11-21)."""

    EVERYBODY, CHOSEN, NOBODY = "everybody", "chosen", "nobody"

    notify = forms.ChoiceField(
        label=_("Notify"),
        choices=[
            (EVERYBODY, _("Everybody in the project")),
            (CHOSEN, _("Only these people")),
            (NOBODY, _("Nobody")),
        ],
        initial=EVERYBODY,
        widget=forms.RadioSelect,
    )
    people = PeopleField(
        label=_("These people"),
        queryset=User.objects.none(),
        widget=PeopleSelect(attrs={"data-placeholder": _("Add people…")}),
    )
    people.shown_when = f"notify={CHOSEN}"

    def __init__(self, *args, project, user, folder=None, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["people"]
        # The members, not the poster: nobody hears about their own posts
        field.queryset = (
            User.objects
            .active()
            .filter(memberships__project=project)
            .exclude(pk=user.pk)
            .order_by(Lower("full_name"), "email")
        )
        if not self.is_bound:
            # Who'd see it as the form starts: in a folder as the folder
            # says, at the top what clients post (``message_visibility()``)
            visible = folder.is_client_visible if folder else user.is_client
            field.initial = [
                person.pk
                for person in everybody(project, folder, visible=visible)
                if person != user
            ]

    def mention_fields(self, project, *names, folder=None):
        """The ``@`` list of the fields: whoever will see the new item"""
        url = reverse("mentionable_new", args=[project.pk])
        if folder:
            url += f"?folder={folder.pk}"
        for name in names:
            attrs = self.fields[name].widget.attrs
            attrs["data-mentions"] = url
            if "visible" in self.fields and not folder:
                attrs["data-mentions-visible"] = "#id_visible"

    def whom(self):
        """What ``notify_people()`` takes"""
        data = self.cleaned_data
        if data["notify"] == self.CHOSEN:
            return list(data["people"])
        return data["notify"]


def comments_context(request, item):
    """Handles the comment form of a page; returns the form, a redirect if
    a comment was added, and the comments"""
    form = CommentForm(request.POST if request.POST.get("form") == "comment" else None)
    form.fields["content"].widget.attrs["data-mentions"] = reverse(
        "mentionable", args=[item.pk]
    )
    if form.is_valid():
        ops.add_comment(item, author=request.user, content=form.cleaned_data["content"])
        return form, redirect(f"{item.get_absolute_url()}#comments")
    return form, None


def sidebar_context(request, item):
    """Subscribers, the switch and the trash button of an item's page"""
    return {
        # Clients only learn about the project's members
        "subscribers": item.project.people_known_to(
            request.user, [s.user for s in item.subscriptions.select_related("user")]
        ),
        "is_subscribed": is_subscribed(request.user, item),
        "is_assigned": is_assigned(request.user, item),
        "can_change": ops.can_change(request.user, item),
        "can_switch": item.has_switch and not request.user.is_client,
    }
