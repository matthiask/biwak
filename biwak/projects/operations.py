"""Members: adding, inviting and removing people (specs/core.md,
specs/access.md). Adding someone subscribes them to nothing that exists
already (specs/notifications.md)."""

from django.conf import settings
from django.core.mail import send_mail
from django.db import connection, transaction
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from biwak.accounts.models import NotificationLevel, User
from biwak.activity.models import Action, LevelOverride, Subscription
from biwak.activity.notify import effective_level
from biwak.activity.operations import record, set_level_override
from biwak.projects.models import Membership


def can_manage_members(user):
    """Staff manage members; clients don't"""
    return user.is_authenticated and not user.is_client


def addable_people(project):
    """Active people who aren't members yet"""
    return User.objects.active().exclude(memberships__project=project)


# How people are in a project (specs/notifications.md, "Notified by default
# or only when tagged"): not a setting of its own, the person's level for
# the project
NOTIFY_DEFAULT, NOTIFY_TAGGED = "default", "tagged"
NOTIFY_CHOICES = {
    NOTIFY_DEFAULT: NotificationLevel.EVERYTHING,
    NOTIFY_TAGGED: NotificationLevel.CONCERNS_ME,
}


def notify_choice(user, project):
    """``default``, ``tagged`` or ``nothing``, from the person's effective
    level for the project"""
    level = effective_level(user, project=project)
    for choice, choice_level in NOTIFY_CHOICES.items():
        if level == choice_level:
            return choice
    return "nothing"


def can_change_notify_choice(actor, user):
    """Staff change everybody's, clients only their own"""
    return actor.is_authenticated and (not actor.is_client or actor == user)


@transaction.atomic
def set_notify_choice(project, user, notify, *, actor):
    """Stores the choice as the person's override for the project"""
    if notify not in NOTIFY_CHOICES:
        raise ValueError(f"Unknown choice {notify!r}")
    if not can_change_notify_choice(actor, user):
        raise PermissionError("Clients change only their own choice.")
    set_level_override(user, NOTIFY_CHOICES[notify], project=project)


@transaction.atomic
def add_member(project, user, *, actor, notify=NOTIFY_DEFAULT):
    """Returns whether the person was added (False if already a member).
    ``notify`` is stored as the person's override for the project, unless
    they have one already: adding again never changes it."""
    if not user.is_active:
        raise ValueError("Inactive people can't be added.")
    if notify not in NOTIFY_CHOICES:
        raise ValueError(f"Unknown choice {notify!r}")
    _membership, created = Membership.objects.get_or_create(project=project, user=user)
    LevelOverride.objects.get_or_create(
        user=user, project=project, defaults={"level": NOTIFY_CHOICES[notify]}
    )
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
def invite(
    project,
    *,
    email,
    actor,
    full_name="",
    is_client=True,
    organization="",
    notify=NOTIFY_DEFAULT,
):
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
    added = add_member(project, user, actor=actor, notify=notify)
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


def can_manage_project(user):
    """Staff edit and archive projects; clients don't"""
    return user.is_authenticated and not user.is_client


@transaction.atomic
def archive_project(project, *, actor):
    """Out of the lists and the feed; everything stays readable"""
    project.archived_at = timezone.now()
    project.save(update_fields=["archived_at"])
    record(actor=actor, action=Action.ARCHIVED, project=project)


@transaction.atomic
def unarchive_project(project, *, actor):
    project.archived_at = None
    project.save(update_fields=["archived_at"])
    record(actor=actor, action=Action.UNARCHIVED, project=project)


# The stored activity times (specs/projects-overview.md). ``record()`` keeps
# them current; this recomputes them from the events: events of trashed
# items don't count, and the client column only counts items visible to
# clients now; reactions don't count, as in ``record()``. Used by ``fairy_tasks`` and the data migration.
RECOMPUTE_ACTIVITY_SQL = """
UPDATE projects_project p SET
  last_activity_at = a.last_activity,
  last_client_activity_at = a.last_client_activity
FROM (
  SELECT p2.id,
    (SELECT max(e.created_at) FROM activity_event e
       LEFT JOIN items_item i ON i.id = e.item_id
       WHERE e.project_id = p2.id AND e.action <> 'reacted'
         AND (i.id IS NULL OR i.status <> 'trashed')
    ) AS last_activity,
    (SELECT max(e.created_at) FROM activity_event e
       JOIN items_item i ON i.id = e.item_id
       WHERE e.project_id = p2.id AND e.action <> 'reacted'
         AND i.status <> 'trashed' AND i.is_client_visible
    ) AS last_client_activity
  FROM projects_project p2
) a
WHERE a.id = p.id AND (
  p.last_activity_at IS DISTINCT FROM a.last_activity
  OR p.last_client_activity_at IS DISTINCT FROM a.last_client_activity
)
"""


def recompute_activity():
    """Returns the number of projects whose times changed"""
    with connection.cursor() as cursor:
        cursor.execute(RECOMPUTE_ACTIVITY_SQL)
        return cursor.rowcount


@transaction.atomic
def set_project_order(user, order):
    """The person's choice on the projects page, remembered"""
    if order not in User.ProjectOrder.values:
        raise ValueError(f"Unknown order {order!r}")
    if user.project_order != order:
        user.project_order = order
        user.save(update_fields=["project_order"])
