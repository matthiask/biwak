"""What the pages of messages, docs and files share"""

from django.db.models.functions import Lower
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User
from biwak.activity.notify import people_who_see, told_by_default, told_line
from biwak.activity.operations import is_assigned, is_subscribed
from biwak.forms import Form, PeopleField, PeopleSelect
from biwak.items import operations as ops
from biwak.items.views import CommentForm


class NotifyForm(Form):
    """Who is told when posting (``notify_people()``, specs/notifications.md,
    decided 2026-11-21: additive): a line saying whom the post tells by
    default (``notify.told_by_default()``, ``told_line()``, the field's
    ``intro``), and "Also tell…", the people picker of those who see it
    and aren't told already, nothing preselected. The poster is neither
    told nor offered."""

    also = PeopleField(
        label=_("Also tell…"),
        queryset=User.objects.none(),
        widget=PeopleSelect(attrs={"data-placeholder": _("Add people…")}),
    )

    def __init__(self, *args, project, user, folder=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Who'd see it: in a folder as the folder says, at the top what
        # clients post (``message_visibility()``)
        visible = folder.is_client_visible if folder else user.is_client
        told = told_by_default(project, folder, visible=visible, actor=user)
        field = self.fields["also"]
        field.intro = told_line(told, project, user)
        field.queryset = (
            people_who_see(project, visible)
            .filter(memberships__project=project)
            .exclude(pk__in=[user.pk, *(person.pk for person in told)])
            .order_by(Lower("full_name"), "email")
        )

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

    def also_people(self):
        """What ``notify_people()`` takes"""
        return list(self.cleaned_data["also"])


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
