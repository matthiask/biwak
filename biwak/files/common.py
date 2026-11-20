"""What the pages of messages, docs and files share"""

from django import forms
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User
from biwak.activity.operations import is_subscribed
from biwak.forms import Form
from biwak.items import operations as ops, visibility
from biwak.items.views import CommentForm


class NotifyForm(Form):
    """ "Whom to notify" when posting (``notify_people()``,
    specs/notifications.md): everybody in the project, chosen people or
    nobody. Everybody is preselected (decided 2026-11-20): the levels keep
    mails away from those who want them only when tagged."""

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
    people = forms.ModelMultipleChoiceField(
        label=_("These people"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["people"].queryset = User.objects.active().filter(
            memberships__project=project
        )

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
        "subscribers": [s.user for s in item.subscriptions.select_related("user")],
        "is_subscribed": is_subscribed(request.user, item),
        "can_change": ops.can_change(request.user, item),
        "can_switch": item.has_switch and not request.user.is_client,
        "affected": visibility.affected(item)
        if item.has_switch and not item.is_client_visible
        else None,
    }
