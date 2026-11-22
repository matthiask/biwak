"""What the pages of messages, docs and files share"""

from django.db.models.functions import Lower
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html_join
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
        field = self.fields["also"]
        seeing = people_who_see(project, visible=True).filter(
            memberships__project=project
        )
        if folder is None and "visible" in self.fields and not user.is_client:
            # At the top staff choose (decided 2026-11-22): the line and
            # the clients offered follow "Visible to clients"
            # (frontend/told.js); both lines, the current one shown
            told = {
                visible: told_by_default(project, None, visible=visible, actor=user)
                for visible in (False, True)
            }
            field.intro_lines = tuple(
                told_line(told[visible], project, user) for visible in (False, True)
            )
            current = self.is_bound and self["visible"].data
            field.intro = format_html_join(
                "",
                '<span data-told="{}"{}>{}</span>',
                [
                    (name, "" if visible == current else " hidden", line)
                    for name, visible, line in zip(
                        ("internal", "visible"),
                        (False, True),
                        field.intro_lines,
                        strict=True,
                    )
                ],
            )
            field.widget.attrs["data-clients-follow"] = "#id_visible"
            field.widget.clients_shown = bool(current)
            told = told[True]
        else:
            # Who'd see it: in a folder as the folder says, at the top what
            # clients post (``message_visibility()``)
            visible = folder.is_client_visible if folder else user.is_client
            told = told_by_default(project, folder, visible=visible, actor=user)
            field.intro_lines = (told_line(told, project, user),)
            field.intro = field.intro_lines[0]
            if not visible:
                seeing = seeing.filter(is_client=False)
        field.queryset = seeing.exclude(
            pk__in=[user.pk, *(person.pk for person in told)]
        ).order_by(Lower("full_name"), "email")

    def clean(self):
        data = super().clean()
        if (
            "visible" in self.fields
            and not data.get("visible")
            and any(person.is_client for person in data.get("also") or ())
        ):
            self.add_error("also", _("Clients can't see it."))
        return data

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
