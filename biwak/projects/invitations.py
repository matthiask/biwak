"""Inviting several people at once, and invitations visible
(specs/activation.md, "Inviting"): one form with a row per person and the
projects for all of them, from "Invite people" on the People page and from
"Invite by email" on a project's people page; resending and withdrawing an
invitation while the person hasn't signed in."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy, ngettext
from django.views.decorators.http import require_POST

from biwak.accounts.models import User
from biwak.forms import Form, next_url
from biwak.modals import form_response
from biwak.organizations.forms import OrganizationFieldMixin, organization_field
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.projects.views import notify_field, project_for


class InviteRow(OrganizationFieldMixin, Form):
    """A person: address, name, organization and, for admins, staff or
    client"""

    email = forms.EmailField(
        label=gettext_lazy("Email"),
        widget=forms.EmailInput(attrs={"placeholder": gettext_lazy("Email")}),
    )
    full_name = forms.CharField(
        label=gettext_lazy("Name"),
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Name")}),
    )
    organization = organization_field()
    is_client = forms.TypedChoiceField(
        label=gettext_lazy("Staff or client"),
        choices=[("1", gettext_lazy("Client")), ("", gettext_lazy("Staff"))],
        coerce=bool,
        empty_value=False,
        initial="1",
        required=False,
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].widget.attrs["placeholder"] = _("Organization")
        if not actor.is_admin:
            # Only admins create staff (specs/access.md)
            del self.fields["is_client"]


class BaseInviteRows(forms.BaseFormSet):
    def person_rows(self):
        """The rows filled in, each with what ``invite_people()`` takes"""
        return [row for row in self.forms if row.has_changed() and row.is_valid()]


# Without JavaScript three rows; "Add another" adds more (invite.js)
InviteRows = forms.formset_factory(
    InviteRow,
    formset=BaseInviteRows,
    extra=2,
    min_num=1,
    validate_min=True,
    max_num=50,
    validate_max=True,
)


class InvitePeopleForm(Form):
    projects = forms.ModelMultipleChoiceField(
        label=gettext_lazy("Projects"),
        queryset=Project.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text=gettext_lazy("Everybody in the rows joins all of them."),
    )
    notify = notify_field()

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["projects"].queryset = (
            Project.objects.accessible_to(actor).active().order_by(Lower("name"))
        )
        self.rows = InviteRows(
            self.data or None, prefix="person", form_kwargs={"actor": actor}
        )

    def is_valid(self):
        valid = super().is_valid()
        return self.rows.is_valid() and valid


def invite_people(request, project=None):
    """The form with the projects and a row per person: a modal, also a
    page; ``project`` is chosen already (a project's people page)"""
    if not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    form = InvitePeopleForm(
        request.POST or None,
        actor=request.user,
        initial={"projects": [project]} if project else None,
    )
    if form.is_valid():
        rows = form.rows.person_rows()
        try:
            # New organizations only with the invitations
            with transaction.atomic():
                invited = project_ops.invite_people(
                    form.cleaned_data["projects"],
                    [
                        {
                            "email": row.cleaned_data["email"],
                            "full_name": row.cleaned_data["full_name"],
                            "is_client": row.cleaned_data.get("is_client", True),
                            "organization": row.organization(request.user),
                        }
                        for row in rows
                    ],
                    actor=request.user,
                    notify=form.cleaned_data["notify"],
                )
        except project_ops.InvitationErrors as exc:
            for index, message in exc.errors.items():
                rows[index].add_error(None, message)
            form.add_error(
                None, _("Nobody has been invited: correct the rows marked below.")
            )
        else:
            messages.success(
                request,
                ngettext(
                    "%(count)s person invited or added.",
                    "%(count)s people invited or added.",
                    len(invited),
                )
                % {"count": len(invited)},
            )
            if project is not None:
                return redirect("project_people", pk=project.pk)
            return redirect(reverse("people") + "?invited=1")
    return form_response(
        request,
        form,
        title=_("Invite people"),
        intro=_(
            "New people get a mail naming the projects and log in with a code"
            " sent to their address; people who have an account are added."
            " Adding someone subscribes them to nothing that exists already."
        ),
        project=project,
        cancel_url=reverse("project_people", args=[project.pk])
        if project
        else reverse("people"),
        submit_label=_("Invite"),
        template="projects/invite.html",
    )


def member_invite(request, pk):
    """ "Invite by email" on a project's people page: the same form, with
    the project chosen"""
    return invite_people(request, project_for(request, pk))


def invitation_for(request, pk):
    """An invitation the person may manage, else 404 (for people who aren't
    invitations) or 403 (clients, externals, staff for staff's)"""
    if not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    user = get_object_or_404(User.objects.invited(), pk=pk)
    if not project_ops.can_manage_invitation(request.user, user):
        raise PermissionDenied
    return user


def back(request, user):
    return next_url(request) or reverse("person", args=[user.pk])


@require_POST
def invitation_resend(request, pk):
    user = invitation_for(request, pk)
    project_ops.resend_invitation(user, actor=request.user)
    messages.success(request, _("Sent again."))
    return redirect(back(request, user))


def withdrawn_projects(withdrawn, *, actor):
    """The projects of ``withdrawn`` for the question: the names of those the
    actor can open, the others counted, not named"""
    projects, others = withdrawn.for_actor(actor)
    names = [p.name for p in projects]
    if others:
        names.append(
            ngettext(
                "%(count)s project you can't open",
                "%(count)s projects you can't open",
                others,
            )
            % {"count": others}
        )
    return ", ".join(names) or _("no projects")


def invitation_withdraw(request, pk):
    """The question, then withdrawing: a modal, also a page"""
    user = invitation_for(request, pk)
    withdrawn = project_ops.withdrawal(user, actor=request.user)
    if request.method == "POST":
        withdrawn = project_ops.withdraw_invitation(user, actor=request.user)
        messages.success(
            request,
            _("The invitation of %(name)s has been withdrawn.")
            % {"name": user.display_name},
        )
        if withdrawn.deleted:
            return redirect(reverse("people") + "?invited=1")
        return redirect(back(request, user))
    names = withdrawn_projects(withdrawn, actor=request.user)
    if withdrawn.deleted:
        intro = _(
            "%(name)s is removed from %(projects)s and the account is deleted:"
            " nothing else refers to it."
        )
    else:
        intro = _(
            "%(name)s is removed from %(projects)s and the account is"
            " deactivated: it stays, since something else refers to it"
            " (comments, assignments)."
        )
    return form_response(
        request,
        None,
        title=_("Withdraw the invitation?"),
        intro=intro % {"name": user.display_name, "projects": names},
        cancel_url=back(request, user),
        submit_label=_("Withdraw"),
        destructive=True,
    )
