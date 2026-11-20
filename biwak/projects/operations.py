"""Members: adding, inviting and removing people (specs/core.md,
specs/access.md). Adding someone subscribes them to nothing that exists
already (specs/notifications.md)."""

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _

from biwak.accounts.models import User
from biwak.activity.models import Action, Subscription
from biwak.activity.operations import record
from biwak.projects.models import Membership


def can_manage_members(user):
    """Staff manage members; clients don't"""
    return user.is_authenticated and not user.is_client


def addable_people(project):
    """Active people who aren't members yet"""
    return User.objects.active().exclude(memberships__project=project)


@transaction.atomic
def add_member(project, user, *, actor):
    """Returns whether the person was added (False if already a member)"""
    if not user.is_active:
        raise ValueError("Inactive people can't be added.")
    _membership, created = Membership.objects.get_or_create(project=project, user=user)
    if created:
        if actor == user:
            record(actor=actor, action=Action.JOINED, project=project)
        else:
            record(
                actor=actor,
                action=Action.ADDED,
                project=project,
                user=user.pk,
                name=user.display_name,
            )
    return created


@transaction.atomic
def remove_member(project, user, *, actor):
    deleted, _rows = Membership.objects.filter(project=project, user=user).delete()
    if not deleted:
        return False
    if actor == user:
        record(actor=actor, action=Action.LEFT, project=project)
    else:
        record(
            actor=actor,
            action=Action.REMOVED,
            project=project,
            user=user.pk,
            name=user.display_name,
        )
    # Without access, their subscriptions in the project go too
    if not project.is_accessible_to(user):
        Subscription.objects.filter(user=user, item__project=project).delete()
    return True


class InvitationError(ValueError):
    pass


@transaction.atomic
def invite(project, *, email, actor, full_name="", is_client=True, organization=""):
    """Adds a person by email address, creating them if they don't exist
    yet and mailing them how to log in. Only admins create staff
    (specs/access.md: staff or client is set by admins). Returns the
    person and whether they were created."""
    email = User.objects.normalize_email(email.strip())
    user = User.objects.filter(email__iexact=email).first()
    created = False
    if user is None:
        if not is_client and not actor.is_admin:
            raise InvitationError(_("Only admins can invite staff."))
        user = User.objects.create_user(
            email,
            full_name=full_name.strip(),
            is_client=is_client,
            organization=organization.strip() if is_client else "",
        )
        created = True
    elif not user.is_active:
        raise InvitationError(_("This person has been deactivated."))
    added = add_member(project, user, actor=actor)
    if created:
        transaction.on_commit(lambda: send_invitation(project, user, actor=actor))
    return user, created or added


def send_invitation(project, user, *, actor):
    context = {
        "project": project,
        "user": user,
        "actor": actor,
        "url": settings.BASE_URL + project.get_absolute_url(),
    }
    # In their language if they have one, else in the inviter's
    with translation.override(user.language or translation.get_language()):
        send_mail(
            _("%(actor)s invited you to %(project)s")
            % {"actor": actor, "project": project},
            render_to_string("projects/invitation.txt", context),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
