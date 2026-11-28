"""Members: adding, inviting and removing people (specs/core.md,
specs/access.md). Adding someone subscribes them to nothing that exists
already (specs/notifications.md)."""

from collections import Counter
from dataclasses import dataclass
from typing import NamedTuple

from django.core.mail import EmailMessage
from django.db import connection, models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from biwak.accounts.languages import language_for, supported
from biwak.accounts.models import Color, NotificationLevel, User
from biwak.activity.mails import sender
from biwak.activity.models import Action, LevelOverride, Subscription
from biwak.activity.notify import effective_level
from biwak.activity.operations import is_importing, record, set_level_override
from biwak.api_conventions import absolute
from biwak.organizations import operations as org_ops
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind
from biwak.projects.models import Membership, Project


def can_manage_members(user):
    """Own staff manage members; clients and externals
    don't (adding offers everybody, which externals mustn't learn about)"""
    return user.is_authenticated and user.sees_all_access


def addable_people(project):
    """Active people who aren't members yet"""
    return User.objects.active().exclude(memberships__project=project)


# How people are in a project (specs/notifications.md, "Notified by default
# or only when tagged"): not a setting of its own, the person's level for
# the project. "default" is the older name of "notified of everything new";
# only when tagged is the default (decided 2026-11-22).
NOTIFY_DEFAULT, NOTIFY_TAGGED = "default", "tagged"
NOTIFY_CHOICES = {
    NOTIFY_TAGGED: NotificationLevel.CONCERNS_ME,
    NOTIFY_DEFAULT: NotificationLevel.EVERYTHING,
}


def notify_choice(user, project):
    """``default`` or ``tagged``, from the person's effective level for the
    project: anything but everything is ``tagged`` (a level stored before
    the levels changed never breaks the pages listing members)"""
    if effective_level(user, project=project) == NOTIFY_CHOICES[NOTIFY_DEFAULT]:
        return NOTIFY_DEFAULT
    return NOTIFY_TAGGED


def can_change_notify_choice(actor, user):
    """Own staff change (and see) everybody's; clients and externals only
    their own (decided 2026-11-21 after a review)"""
    return actor.is_authenticated and (can_manage_members(actor) or actor == user)


@transaction.atomic
def set_notify_choice(project, user, notify, *, actor):
    """Stores the choice as the person's override for the project"""
    if notify not in NOTIFY_CHOICES:
        raise ValueError(f"Unknown choice {notify!r}")
    if not can_change_notify_choice(actor, user):
        raise PermissionError("Clients and externals change only their own choice.")
    set_level_override(user, NOTIFY_CHOICES[notify], project=project)


@transaction.atomic
def add_member(project, user, *, actor, notify=NOTIFY_TAGGED):
    """Returns whether the person was added (False if already a member).
    ``notify`` is stored as the person's override for the project, unless
    they have one already: adding again never changes it."""
    if not user.is_active and not is_importing():
        raise ValueError("Inactive people can't be added.")
    if project.is_template:
        # The people come with the project, not the template
        # (specs/templates.md)
        raise ValueError(_("Templates have no members."))
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
    """Takes the person out of the project, off its open to-dos too
    (decided 2026-11-21); records "removed", or "left" for oneself"""
    from biwak.items import operations as item_ops

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
    item_ops.unassign_dropped(user, actor=actor, project=project)
    return True


def forget_lost_access(user, *, project=None):
    """Without access, the person's subscriptions go (in ``project``, or in
    every project): removed from a limited project, or no longer the
    own staff (specs/access.md)"""
    subscriptions = Subscription.objects.filter(user=user)
    if project is not None:
        subscriptions = subscriptions.filter(item__project=project)
    subscriptions.exclude(
        item__project__in=Project.objects.accessible_to(user)
    ).delete()


class InvitationError(ValueError):
    pass


class InvitationErrors(InvitationError):
    """What ``invite_people()`` refused, ``{row's index: message}``; nothing
    of the round was saved"""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(" ".join(errors.values()))


@dataclass
class Invited:
    user: User
    created: bool  # A new person, mailed the invitation
    added_to: list  # The projects they weren't in yet


def _invitee(email, *, actor, full_name, is_client, organization):
    """The person with ``email``, created if they don't exist yet; raises
    ``InvitationError`` for what the actor may not do. Returns the person
    and whether they were created."""
    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        if user.left_at is not None:
            raise InvitationError(
                _("This person has been deactivated: activate them first.")
            )
        if not user.is_active and not user.is_client and not actor.is_admin:
            # Waiting to be activated: who may activate them (decided
            # 2026-11-28, ``activation.can_change()``)
            raise InvitationError(_("Only admins can invite staff."))
        return user, False
    if not is_client and not actor.is_admin:
        raise InvitationError(_("Only admins can invite staff."))
    if organization is not None and not org_ops.can_touch(actor, organization):
        raise InvitationError(
            _(
                "Only admins add people to your own organization or an external"
                " organization."
            )
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
        invited_by=actor,
        invited_at=timezone.now(),
    )
    return user, True


@transaction.atomic
def invite_people(projects, people, *, actor, notify=NOTIFY_TAGGED):
    """Invites ``people`` (dicts of ``email`` and optionally ``full_name``,
    ``is_client``, default True, and ``organization``) to every one of
    ``projects`` (specs/activation.md, "Inviting"). New people are created and
    mailed one invitation naming the projects, after the commit; people who
    have an account are added (``add_member()``, which records it), no
    invitation. ``notify`` is the choice for every project. All or nothing:
    ``InvitationErrors`` with each refused row's message, and nothing saved.
    Only admins create staff (specs/access.md: staff or client is set by
    admins). New people belong to their ``organization``, else to the one
    their address's domain belongs to (specs/organizations.md); only admins
    put people into the own. People who exist keep theirs. People waiting
    to be activated are activated and mailed the invitation like
    activating with the mail; people who left are refused."""
    if not can_manage_members(actor):
        raise PermissionError("Only staff invite people.")
    if notify not in NOTIFY_CHOICES:
        raise ValueError(f"Unknown choice {notify!r}")
    from biwak.organizations import activation

    projects = list(projects)
    errors, done, seen, waiting = {}, [], set(), []
    for index, row in enumerate(people):
        email = User.objects.normalize_email(row["email"].strip())
        if email.lower() in seen:
            errors[index] = _("This address is in another row too.")
            continue
        seen.add(email.lower())
        try:
            user, created = _invitee(
                email,
                actor=actor,
                full_name=row.get("full_name", ""),
                is_client=row.get("is_client", True),
                organization=row.get("organization"),
            )
        except InvitationError as exc:
            errors[index] = str(exc)
            continue
        if not user.is_active:
            # Waiting to be activated (an import's): activated, and sent the
            # invitation below (decided 2026-11-28)
            activation.activate([user], actor=actor)
            user.refresh_from_db()
            waiting.append(user)
        added = [
            project
            for project in projects
            if add_member(project, user, actor=actor, notify=notify)
        ]
        done.append(Invited(user, created, added))
    if errors:
        # Rolls the round back; no mail is queued before this
        raise InvitationErrors(errors)
    for invited in done:
        if invited.created:
            # Through the outbox: sent once this commits, not on a rollback
            send_invitation(projects, invited.user, actor=actor)
    for user in waiting:
        # As activating with the mail: the projects they're in now
        activation.mail_invitation(user, actor=actor)
    return done


def invite(
    project,
    *,
    email,
    actor,
    full_name="",
    is_client=True,
    organization=None,
    notify=NOTIFY_TAGGED,
):
    """``invite_people()`` for one person and one project (the API's
    ``members/invite/``, the new project's rows). Returns the person and
    whether they were created or added."""
    try:
        [invited] = invite_people(
            [project],
            [
                {
                    "email": email,
                    "full_name": full_name,
                    "is_client": is_client,
                    "organization": organization,
                }
            ],
            actor=actor,
            notify=notify,
        )
    except InvitationErrors as exc:
        raise InvitationError(exc.errors[0]) from exc
    return invited.user, invited.created or bool(invited.added_to)


def invitation_projects(user):
    """The projects an invitation names when it's sent again: those the
    person is in now, not archived"""
    return Project.objects.filter(
        memberships__user=user, archived_at__isnull=True
    ).order_by(Lower("name"))


def can_manage_invitation(actor, user):
    """Resending and withdrawing invitations, while the person hasn't signed
    in yet: the split of ``activation.can_change()``, staff for clients,
    admins for everybody"""
    from biwak.organizations import activation

    return user.is_invited and activation.can_change(actor, user)


def resend_invitation(user, *, actor):
    """The invitation mail again, naming the projects the person is in now
    (no limit in code, decided 2026-11-21); after the commit"""
    if not can_manage_invitation(actor, user):
        raise PermissionError(
            "Only staff resend invitations of clients not signed in, admins"
            " everybody's."
        )
    # Through the outbox: sent once this commits
    send_invitation(list(invitation_projects(user)), user, actor=actor)


def _referred_to(user, *, leaving=()):
    """Whether something keeps the person: what can't be deleted with
    them (comments, items, events, files, links: ``PROTECT``), what others
    gave them (assignments, check-ins asking them), mentions and reactions.
    Not the assignments on open to-dos of the projects they're ``leaving``,
    which ``remove_member()`` takes away (decided 2026-11-28)."""
    from biwak.activity.models import Mention
    from biwak.items.models import Todo
    from biwak.reactions.models import Reaction

    for relation in User._meta.get_fields(include_hidden=True):
        if not (relation.auto_created and relation.is_relation) or relation.concrete:
            continue
        if relation.many_to_many or relation.on_delete is models.PROTECT:
            manager = relation.related_model._base_manager
            rows = manager.filter(**{relation.field.name: user})
            if relation.related_model is Todo:
                rows = rows.exclude(
                    completed_at__isnull=True, item__project__in=list(leaving)
                )
            if rows.exists():
                return True
    return (
        Mention.objects.filter(user=user).exists()
        or Reaction.objects.filter(user=user).exists()
    )


class Withdrawn(NamedTuple):
    """What withdrawing an invitation does (or did)"""

    # The projects the person is removed from: all of theirs (decided
    # 2026-11-21: "withdrawing is withdrawing")
    projects: list
    # The account goes: nothing refers to it
    deleted: bool
    # The account stays but is deactivated: something refers to it (decided
    # 2026-11-21)
    deactivated: bool

    def for_actor(self, actor):
        """The projects the actor can open, and how many others there are
        (named to nobody who can't open them)"""
        accessible = set(
            Project.objects
            .accessible_to(actor)
            .filter(pk__in=[p.pk for p in self.projects])
            .values_list("pk", flat=True)
        )
        names = [p for p in self.projects if p.pk in accessible]
        return names, len(self.projects) - len(names)


def withdrawal(user, *, actor):
    """What withdrawing the invitation does (``Withdrawn``): removed from
    all their projects, also those the actor can't open (decided
    2026-11-21); the account deleted when nothing else refers to it
    (``_referred_to()``), deactivated when something does"""
    projects = list(
        Project.objects.filter(memberships__user=user).order_by(Lower("name"))
    )
    referred_to = _referred_to(user, leaving=projects)
    return Withdrawn(projects, deleted=not referred_to, deactivated=referred_to)


@transaction.atomic
def withdraw_invitation(user, *, actor):
    """Removes the invited person from all their projects
    (``withdrawal()``); the account goes too, or is deactivated
    (``activation.deactivate()``, decided 2026-11-21: sessions, tokens and
    calendar links go). Staff for clients, admins
    for everybody, while the person hasn't signed in. The feed's "added"
    events stay. Returns ``Withdrawn``."""
    from biwak.organizations import activation

    if not can_manage_invitation(actor, user):
        raise PermissionError(
            "Only staff withdraw invitations of clients not signed in, admins"
            " everybody's."
        )
    projects = withdrawal(user, actor=actor).projects
    for project in projects:
        # Unassigns them from the open to-dos before deciding (decided
        # 2026-11-28)
        remove_member(project, user, actor=actor)
    referred_to = _referred_to(user)
    if referred_to:
        activation.deactivate([user], actor=actor)
    else:
        user.delete()
    return Withdrawn(projects, deleted=not referred_to, deactivated=referred_to)


def send_invitation(projects, user, *, actor):
    """The invitation mail naming ``projects``"""
    projects = list(projects)
    context = {
        "projects": [
            {"name": project.name, "url": absolute(project.get_absolute_url())}
            for project in projects
        ],
        "user": user,
        "actor": actor,
        "url": absolute(projects[0].get_absolute_url() if len(projects) == 1 else "/"),
    }
    # In their language if they chose one, else in the inviter's, which
    # later mails use too until they choose (specs/languages.md)
    if not user.language:
        user.invitation_language = supported(translation.get_language())
        user.save(update_fields=["invitation_language"])
    with translation.override(language_for(user)):
        if len(projects) == 1:
            subject = _("%(actor)s invited you to %(project)s") % {
                "actor": actor,
                "project": projects[0],
            }
        else:
            subject = _("%(actor)s invited you to Biwak") % {"actor": actor}
        message = EmailMessage(
            subject,
            render_to_string("projects/invitation.txt", context),
            # From the person inviting, like notification mails
            sender(_("%(name)s (Biwak)") % {"name": actor}),
            [user.email],
        )
    outbox.send(message, MailKind.INVITATION)


def can_manage_project(user):
    """Staff edit and archive projects; clients don't"""
    return user.is_authenticated and not user.is_client


def can_create_project(user):
    """Own staff: the form offers the organizations and
    their people, which externals mustn't learn about"""
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


# Templates (specs/templates.md) ----------------------------------------------


def can_use_templates(user):
    """Own staff see, use and change all templates; clients and externals
    never see them"""
    return user.is_authenticated and user.sees_all_access


@transaction.atomic
def create_template(*, name, description="", color="", actor):
    """A template: all-access, without members, never switched to a
    project"""
    if not can_use_templates(actor):
        raise PermissionError("Only own staff create templates.")
    project = Project(
        name=name.strip(),
        description=description,
        is_all_access=True,
        color=color,
        is_template=True,
    )
    project.full_clean()
    project.save()
    return project


@transaction.atomic
def fill_from_template(project, template, *, actor):
    """Copies the template into the new ``project``
    (``items.operations.copy_template()``) and records the one event
    "created Website from the template Web project". Assignees who
    wouldn't see the copy are added as members, as "Copy…" does."""
    from biwak.items import operations as item_ops

    if not can_use_templates(actor):
        raise PermissionError("Only own staff use templates.")
    item_ops.copy_template(template, project, actor=actor)
    return record(
        actor=actor,
        action=Action.CREATED,
        project=project,
        template=template.name,
        template_id=template.pk,
    )


@transaction.atomic
def create_from_template(template, *, actor, members=(), **fields):
    """A new project (``create_project()`` with ``fields``) with
    ``members`` and everything the template holds"""
    project = create_project(actor=actor, **fields)
    for user in members:
        add_member(project, user, actor=actor)
    fill_from_template(project, template, actor=actor)
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
    in the project go, as in ``remove_member()``. ``actor`` None: nobody,
    only for the importer (a change brought over from Basecamp, which never
    says who made it, specs/import-basecamp.md)."""
    if not (actor is None and is_importing()) and not can_manage_project(actor):
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
    if limited and project.is_template:
        raise ValueError(_("Templates are for all staff."))
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
    join them (specs/access.md); nobody else does. Admins are always the
    own staff (decided 2026-11-21)"""
    if not (user.is_authenticated and user.is_admin):
        return Project.objects.none()
    return Project.objects.active().exclude(pk__in=Project.objects.accessible_to(user))


def projects_to_join(user):
    """What somebody can join: the projects they can open, and for admins
    the limited ones ``joinable_projects()`` lists (not archived ones);
    no templates, which have no members (specs/templates.md)"""
    return Project.objects.filter(
        Q(pk__in=Project.objects.accessible_to(user).values("pk"))
        | Q(pk__in=joinable_projects(user).values("pk")),
        is_template=False,
    )


@transaction.atomic
def archive_project(project, *, actor):
    """Out of the lists and the feed; everything stays readable. Its
    public links end for good (specs/public-links.md)."""
    from biwak.public_links.operations import end_links

    end_links(project=project)
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
