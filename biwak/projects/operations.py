"""Members: adding, inviting and removing people (specs/core.md,
specs/access.md). Adding someone subscribes them to nothing that exists
already (specs/notifications.md)."""

from collections import Counter

from django.conf import settings
from django.core.mail import send_mail
from django.db import connection, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from biwak.accounts.models import Color, NotificationLevel, User
from biwak.activity.models import Action, LevelOverride, Subscription
from biwak.activity.notify import effective_level
from biwak.activity.operations import is_importing, record, set_level_override
from biwak.api_conventions import absolute
from biwak.organizations import operations as org_ops
from biwak.projects.models import Membership, Project


def can_manage_members(user):
    """The installation's own staff manage members; clients and partners
    don't (adding offers everybody, which partners mustn't learn about)"""
    return user.is_authenticated and user.sees_all_access


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
    if not user.is_active and not is_importing():
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
    forget_lost_access(user, project=project)
    return True


def forget_lost_access(user, *, project=None):
    """Without access, the person's subscriptions go (in ``project``, or in
    every project): removed from a limited project, or no longer the
    installation's own staff (specs/access.md)"""
    subscriptions = Subscription.objects.filter(user=user)
    if project is not None:
        subscriptions = subscriptions.filter(item__project=project)
    subscriptions.exclude(
        item__project__in=Project.objects.accessible_to(user)
    ).delete()


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
    organization=None,
    notify=NOTIFY_DEFAULT,
):
    """Adds a person by email address, creating them if they don't exist
    yet and mailing them how to log in. Only admins create staff
    (specs/access.md: staff or client is set by admins). New people belong
    to ``organization``, else to the one their address's domain belongs to
    (specs/organizations.md); only admins put people into the
    installation's own. People who exist keep theirs. Returns the person
    and whether they were created."""
    email = User.objects.normalize_email(email.strip())
    user = User.objects.filter(email__iexact=email).first()
    created = False
    if user is None:
        if not is_client and not actor.is_admin:
            raise InvitationError(_("Only admins can invite staff."))
        if organization is not None and not org_ops.can_touch(actor, organization):
            raise InvitationError(
                _("Only admins add people to the installation's own organization.")
            )
        organization = org_ops.for_new_person(email, organization)
        if organization is not None and not org_ops.can_touch(actor, organization):
            # Suggested by the domain only: not for others than admins
            organization = None
        user = User.objects.create_user(
            email,
            full_name=full_name.strip(),
            is_client=is_client,
            organization=organization,
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
        "url": absolute(project.get_absolute_url()),
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


def can_create_project(user):
    """The installation's own staff: the form offers the organizations and
    their people, which partners mustn't learn about"""
    return user.is_authenticated and user.sees_all_access


@transaction.atomic
def suggested_color():
    """A color of the palette which no active project has, the one used
    least when all are taken; the first in the palette's order on ties"""
    used = Counter(
        Project.objects.active().exclude(color="").values_list("color", flat=True)
    )
    return min(Color.values, key=lambda name: used[name])


def create_project(*, name, description="", is_all_access=True, color=None, actor):
    """The creator becomes a member (``can_create_project()``). Without
    ``color`` the project gets ``suggested_color()``; ``""`` is none."""
    if not can_create_project(actor):
        raise PermissionError("Only staff create projects.")
    project = Project(
        name=name.strip(),
        description=description,
        is_all_access=is_all_access,
        color=suggested_color() if color is None else color,
    )
    project.full_clean()
    project.save()
    Membership.objects.create(project=project, user=actor)
    return project


_UNCHANGED = object()


@transaction.atomic
def update_project(
    project,
    *,
    actor,
    name=_UNCHANGED,
    description=_UNCHANGED,
    is_all_access=_UNCHANGED,
    color=_UNCHANGED,
):
    """Changes what's given and differs (staff only); raises
    ``ValidationError`` for what the model refuses. Making the project
    limited takes access from staff who aren't members: their subscriptions
    in the project go, as in ``remove_member()``."""
    if not can_manage_project(actor):
        raise PermissionError("Only staff change projects.")
    given = {
        "name": name if name is _UNCHANGED else name.strip(),
        "description": description,
        "is_all_access": is_all_access,
        "color": color,
    }
    fields = [
        field
        for field, value in given.items()
        if value is not _UNCHANGED and value != getattr(project, field)
    ]
    if not fields:
        return project
    limited = "is_all_access" in fields and not is_all_access
    for field in fields:
        setattr(project, field, given[field])
    project.full_clean()
    project.save(update_fields=fields)
    record(actor=actor, action=Action.EDITED_PROJECT, project=project)
    if limited:
        Subscription.objects.filter(item__project=project).exclude(
            user__memberships__project=project
        ).delete()
    return project


def joinable_projects(user):
    """Limited projects an admin isn't in: they see that they exist and can
    join them (specs/access.md); nobody else does, partners who are admins
    neither (they're added by the installation's own staff)"""
    if not (user.is_authenticated and user.is_admin and user.sees_all_access):
        return Project.objects.none()
    return Project.objects.active().exclude(pk__in=Project.objects.accessible_to(user))


def projects_to_join(user):
    """What somebody can join: the projects they can open, and for admins
    the limited ones ``joinable_projects()`` lists (not archived ones)"""
    return Project.objects.filter(
        Q(pk__in=Project.objects.accessible_to(user).values("pk"))
        | Q(pk__in=joinable_projects(user).values("pk"))
    )


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
