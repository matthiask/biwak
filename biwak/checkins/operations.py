"""Check-ins (specs/checkins.md): creating and changing questions, asking
them on schedule, summarizing, answering. There are no
reminders for missed check-ins (decided 2026-11-20).

Every change goes through here. ``ask_due()`` and ``summarize_due()`` are
what ``./manage.py send_mails`` runs every minute (see ``run()``): nothing
runs in threads or on requests.
"""

import datetime as dt
import logging

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.translation import gettext

from biwak import schedules
from biwak.accounts.models import User
from biwak.accounts.quiet import is_away, mails_held
from biwak.activity import mentions
from biwak.activity.models import Action, Subscription
from biwak.activity.notify import can_see, who_can_see
from biwak.activity.operations import (
    is_importing,
    read_by_acting,
    record,
    subscribe,
)
from biwak.checkins import mails, schedule
from biwak.checkins.models import (
    DEFAULT_MODE,
    Answer,
    HeldSummary,
    Mode,
    Occurrence,
    Question,
    QuestionMail,
)
from biwak.files import attachments
from biwak.items import editing, operations as items_ops
from biwak.items.models import Item, Kind, Status
from biwak.projects.models import knows_people_of


logger = logging.getLogger(__name__)

# The morning after an occurrence the summary goes out at this time, in the
# installation's time zone (decided 2026-11-20)
SUMMARY_AT = dt.time(7, 0)

_UNCHANGED = object()


class NotAllowed(Exception):
    """The person isn't asked this question (views and the API answer 403)"""


# Who -------------------------------------------------------------------------


def can_answer(user, item):
    """Anybody who can see the question, asked or not (decided 2026-11-21,
    specs/checkins.md): the people asked are who gets asked, reminded and
    has it "due"; clients only questions visible to them"""
    return user.is_active and can_see(user, item)


def _check_people(item, people, *, actor, kept=()):
    """Only people who can see the question are asked, and by clients
    (``actor``) only members, whom they may know (specs/access.md; externals
    know the project's people, decided 2026-11-21). ``kept``: people
    already in the list, who stay when the question turns internal
    (clients aren't asked then, but aren't removed) and when somebody who
    knows only members edits the list. The error names nobody: the IDs come
    from the API."""
    knows = knows_people_of(actor, item.project) or is_importing()
    candidates = who_can_see(item).filter(pk__in=[u.pk for u in people])
    if not knows:
        candidates = candidates.filter(memberships__project=item.project)
    allowed = set(candidates)
    allowed |= {u for u in kept if u.is_client}
    if not knows:
        allowed |= {u for u in kept if not u.is_client}
    for user in people:
        if user not in allowed:
            raise ValueError(
                gettext("Only people who can see the check-in can be asked.")
            )


def _newer():
    """Occurrences of the same question with a later date"""
    return Occurrence.objects.filter(
        question=OuterRef("question"), date__gt=OuterRef("date")
    )


# Questions -------------------------------------------------------------------


@transaction.atomic
def create_question(
    *,
    project,
    title,
    creator,
    rule,
    starts_on,
    time_of_day,
    people=(),
    visible=False,
    now=None,
):
    """Asks the first time on or after ``starts_on`` at ``time_of_day``
    (later than ``now``)"""
    rule = schedules.validate(rule)
    item = items_ops.create_item(
        project=project,
        kind=Kind.QUESTION,
        title=title,
        creator=creator,
        visible=visible,
        position=0,  # Questions are ordered by title
    )
    _check_people(item, people, actor=creator)
    question = Question.objects.create(
        item=item,
        rule=rule,
        starts_on=starts_on,
        time_of_day=time_of_day,
    )
    question.next_at = schedule.next_fire_of(question, after=now or timezone.now())
    question.save(update_fields=["next_at"])
    items_ops.created(item, creator)
    set_people(item, people, actor=creator)
    # Its subscribers, who hear about the answers, are a list of their own;
    # at first the people asked and the creator (proposed 2026-11-21,
    # specs/checkins.md)
    for user in people:
        subscribe(user, item, added_by=creator)
    return item


@transaction.atomic
def copy_question(item, project, *, actor, now=None):
    """A copy of the question in ``project``, a new project from a template
    (specs/templates.md): its schedule as it is (paused or not, asked
    from the next date on) and the people asked, those who wouldn't see
    it there added as members, as for assignees (``people_plan()``).
    Created silently: no event; the creator and the people asked
    subscribed, as by ``create_question()``. Not its answers."""
    from biwak.projects import operations as project_ops

    source = item.question
    copy = items_ops.create_item(
        project=project,
        kind=Kind.QUESTION,
        title=item.title,
        creator=actor,
        visible=item.visible_to_clients,
        position=0,
    )
    visible = copy.visible_to_clients
    asked = source.people.all()
    added, _dropped = items_ops.people_plan(
        asked, User.objects.none(), project, visible
    )
    for user in added:
        project_ops.add_member(project, user, actor=actor)
    people = list(asked.filter(items_ops.staying(project, visible)))
    now = now or timezone.now()
    question = Question.objects.create(
        item=copy,
        rule=source.rule,
        starts_on=source.starts_on,
        time_of_day=source.time_of_day,
        paused_at=now if source.paused_at else None,
    )
    if question.paused_at is None:
        question.next_at = schedule.next_fire_of(question, after=now)
        question.save(update_fields=["next_at"])
    question.people.set(people)
    subscribe(actor, copy)
    # Deactivated people stay in the list, as on the template, but aren't
    # asked (``_recipients()``) and can't be subscribed
    for user in people:
        if user.is_active:
            subscribe(user, copy, added_by=actor)
    return copy


@transaction.atomic
def set_people(item, people, *, actor):
    """The complete set of people asked, from the next occurrence on. Only
    who gets asked: the subscribers, who hear about the answers, are a list
    of their own (decided 2026-11-21, specs/checkins.md)."""
    question = Question.objects.select_for_update().get(item=item)
    people = list(people)
    old = set(question.people.all())
    _check_people(item, people, actor=actor, kept=old)
    new = set(people)
    question.people.set(new)
    return sorted(new - old, key=lambda u: u.pk)


@transaction.atomic
def update_question(
    item,
    *,
    actor,
    title=_UNCHANGED,
    rule=_UNCHANGED,
    starts_on=_UNCHANGED,
    time_of_day=_UNCHANGED,
    people=_UNCHANGED,
    now=None,
):
    """Changes what's given. A new
    schedule counts from now: today's time of day only if it's still ahead,
    and a date already asked isn't asked again."""
    question = (
        Question.objects.select_for_update().select_related("item").get(item=item)
    )
    changed = []
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = timezone.now()
        item.save(update_fields=["title", "updated_at"])
        # Answers carry the question as their title (feed, search, events)
        Item.objects.filter(parent=item, kind=Kind.ANSWER).update(title=title)
        changed.append("title")
    if rule is not _UNCHANGED:
        rule = schedules.validate(rule)
    given = {
        "rule": rule,
        "starts_on": starts_on,
        "time_of_day": time_of_day,
    }
    schedule_changed = False
    for name, value in given.items():
        if value is not _UNCHANGED and getattr(question, name) != value:
            setattr(question, name, value)
            changed.append(name)
            schedule_changed = True
    if schedule_changed and question.paused_at is None:
        question.next_at = schedule.next_fire_of(question, after=now or timezone.now())
        changed.append("next_at")
    fields = [c for c in changed if c != "title"]
    if fields:
        question.save(update_fields=fields)
    if changed:
        record(actor=actor, action=Action.EDITED, project=item.project, item=item)
        read_by_acting(actor, item)
    if people is not _UNCHANGED:
        set_people(item, people, actor=actor)
    return item


@transaction.atomic
def pause(item, *, actor):
    """A paused question isn't asked"""
    question = Question.objects.select_for_update().get(item=item)
    if question.paused_at is not None:
        return
    question.paused_at = timezone.now()
    question.next_at = None
    question.save(update_fields=["paused_at", "next_at"])
    record(actor=actor, action=Action.EDITED, project=item.project, item=item)


@transaction.atomic
def resume(item, *, actor, now=None):
    """Asks again from the next date on; what was missed meanwhile isn't
    asked"""
    question = Question.objects.select_for_update().get(item=item)
    if question.paused_at is None:
        return
    question.paused_at = None
    question.next_at = schedule.next_fire_of(question, after=now or timezone.now())
    question.save(update_fields=["paused_at", "next_at"])
    record(actor=actor, action=Action.EDITED, project=item.project, item=item)


@transaction.atomic
def resume_all(project, *, actor, now=None):
    """Resumes the project's paused questions together, each one's next
    date computed as for a single ``resume()`` (the importer leaves them
    paused, decided 2026-11-21). Returns the questions' items resumed."""
    now = now or timezone.now()
    paused = Item.objects.filter(
        project=project,
        kind=Kind.QUESTION,
        trashed_at__isnull=True,
        question__paused_at__isnull=False,
    ).order_by("title", "pk")
    items = list(paused)
    for item in items:
        resume(item, actor=actor, now=now)
    return items


# Asking and summarizing ------------------------------------------------------


def _recipients(question, occurrence=None):
    """Active people asked who can see the question now (a client doesn't
    once it's internal), and, with an ``occurrence``, were asked then"""
    people = question.people.filter(pk__in=who_can_see(question.item).values("pk"))
    if occurrence is not None:
        people = people.filter(pk__in=occurrence.asked.values("pk"))
    return list(people.select_related("organization").order_by("pk"))


def _answered_ids(occurrence):
    """People who answered (an answer in the trash doesn't count)"""
    answered = Answer.objects.filter(occurrence=occurrence).not_trashed()
    return set(answered.values_list("author", flat=True))


def missing(occurrence):
    """Those asked who haven't answered, still asked and still
    allowed to see the question"""
    done = _answered_ids(occurrence)
    return [u for u in _recipients(occurrence.question, occurrence) if u.pk not in done]


def ask_due(*, now=None):
    """Asks the questions due: one occurrence for the latest date due, mail
    to the people (after the commit), the next time computed. Questions
    which can't be asked (paused ones have no next time; trashed, archived
    or in archived projects) move on without asking. Returns the
    occurrences created."""
    now = now or timezone.now()
    due = list(
        Question.objects
        .filter(next_at__lte=now, paused_at__isnull=True)
        .order_by("next_at", "pk")
        .values_list("pk", flat=True)
    )
    created = []
    for pk in due:
        with transaction.atomic():
            question = (
                Question.objects
                .select_for_update(skip_locked=True, of=("self",))
                .select_related("item__project")
                .filter(pk=pk, next_at__lte=now, paused_at__isnull=True)
                .first()
            )
            if question is None:
                continue
            date, _fire = schedule.latest_due(question, first=question.next_at, now=now)
            if question.is_askable:
                occurrence = _ask(question, date, now)
                if occurrence is not None:
                    created.append(occurrence)
            question.next_at = schedule.next_fire_of(question, after=now)
            question.save(update_fields=["next_at"])
    return created


def _ask(question, date, now):
    """The occurrence of the rule's ``date``, unless it was asked already
    (the schedule was edited on the day)"""
    occurrence, was_created = Occurrence.objects.get_or_create(
        question=question, date=date, defaults={"asked_at": now}
    )
    if not was_created:
        return None
    # People away aren't asked: no mail, not missing (specs/quiet-hours.md)
    today = timezone.localdate(now)
    people = [person for person in _recipients(question) if not is_away(person, today)]
    occurrence.asked.set(people)
    mails.after_commit(mails.question_mail, occurrence, people)
    return occurrence


def summary_due_at(occurrence):
    """07:00 on the day after the occurrence's date, in the installation's
    time zone; after downtime, the day after it was really asked (people
    can answer first)"""
    time_zone = schedule.time_zone()
    day = max(occurrence.date, schedule.local_date(occurrence.asked_at, time_zone))
    return schedule.fire_at(day + dt.timedelta(days=1), SUMMARY_AT, time_zone)


def summary_recipients(question):
    """Subscribers of the question who get summaries (the default mode) and
    see it, whatever their level: subscribing is the switch (decided
    2026-11-21, specs/checkins.md, "Decided")"""
    item = question.item
    people = list(
        User.objects
        .filter(pk__in=Subscription.objects.filter(item=item).values("user"))
        .filter(pk__in=who_can_see(item).values("pk"))
        .order_by("pk")
    )
    modes = dict(
        QuestionMail.objects.filter(question=question, user__in=people).values_list(
            "user", "mode"
        )
    )
    return [user for user in people if modes.get(user.pk, DEFAULT_MODE) == Mode.SUMMARY]


def summarize_due(*, now=None):
    """One mail per person the morning after an occurrence with all its
    answers; none for an occurrence nobody answered. Returns the
    occurrences summarized."""
    now = now or timezone.now()
    pending = Occurrence.objects.filter(
        summarized_at__isnull=True, asked_at__lte=now
    ).select_related("question__item__project")
    done = []
    for occurrence in pending.order_by("pk"):
        if summary_due_at(occurrence) > now:
            continue
        with transaction.atomic():
            locked = (
                Occurrence.objects
                .select_for_update(skip_locked=True, of=("self",))
                .filter(pk=occurrence.pk, summarized_at__isnull=True)
                .first()
            )
            if locked is None:
                continue
            locked.summarized_at = now
            locked.save(update_fields=["summarized_at"])
            answers = answers_of(occurrence)
            if answers:
                people = summary_recipients(occurrence.question)
                # Waiting while their mails wait (specs/quiet-hours.md)
                held = [person for person in people if mails_held(person, now)]
                HeldSummary.objects.bulk_create(
                    [HeldSummary(occurrence=locked, user=person) for person in held],
                    ignore_conflicts=True,
                )
                people = [person for person in people if person not in held]
                if people:
                    mails.after_commit(mails.summary_mail, occurrence, people)
            done.append(occurrence)
    return done


def send_held_summaries(*, now=None):
    """The summaries which waited, to those who may get mail now; returns
    how many people's"""
    now = now or timezone.now()
    count = 0
    for held in HeldSummary.objects.select_related(
        "user", "occurrence__question__item"
    ).order_by("pk"):
        if mails_held(held.user, now):
            continue
        with transaction.atomic():
            if not HeldSummary.objects.filter(pk=held.pk).delete()[0]:
                continue
            mails.after_commit(mails.summary_mail, held.occurrence, [held.user])
        count += 1
    return count


def run(*, now=None):
    """What ``send_mails`` does about check-ins; returns the counts (the
    summaries which waited count as summarized)"""
    now = now or timezone.now()
    return {
        "asked": len(ask_due(now=now)),
        "summarized": len(summarize_due(now=now)) + send_held_summaries(now=now),
    }


# Answering -------------------------------------------------------------------


def answers_of(occurrence):
    """The occurrence's answers, newest first, without those in the trash"""
    return list(
        Answer.objects
        .filter(occurrence=occurrence)
        .not_trashed()
        .select_related("item__creator")
        .order_by("-item__created_at", "-pk")
    )


def latest_occurrence(item):
    """The question's latest ``Occurrence`` (``schedule.latest_due()`` is
    the date the rule asks)"""
    return (
        Occurrence.objects.filter(question__item=item).order_by("-date", "-pk").first()
    )


def _occurrence(item, occurrence):
    """The occurrence to answer: the latest by default"""
    if occurrence is None:
        occurrence = latest_occurrence(item)
        if occurrence is None:
            raise ValueError(gettext("The question hasn't been asked yet."))
    elif occurrence.question_id != item.pk:
        raise ValueError(gettext("The occurrence belongs to another question."))
    return occurrence


@transaction.atomic
def answer(item, *, user, content, occurrence=None, base=None):
    """The person's answer to the occurrence (default: the latest): creates
    it, or changes the one they gave (``Answer`` is unique per occurrence
    and person); answering brings an answer from the trash
    back. ``NotAllowed`` unless they see the question. The author is
    subscribed to their own answer (``create_item()``), so comments on it
    reach them; not to the question, whose subscribers stay the deliberate
    list (decided 2026-11-21, specs/checkins.md)."""
    if not can_answer(user, item):
        raise NotAllowed(f"{user} can't answer {item}")
    occurrence = _occurrence(item, occurrence)
    # Serializes answers to one occurrence (the constraint would catch a race)
    Occurrence.objects.select_for_update().get(pk=occurrence.pk)
    existing = (
        Answer.objects
        .select_related("item")
        .filter(occurrence=occurrence, author=user)
        .first()
    )
    if existing is None:
        answer_item = create_answer(item, user, content, occurrence)
        read_by_acting(user, item, answer_item)
        return answer_item
    answer_item = existing.item
    if answer_item.status == Status.TRASHED:
        items_ops.restore(answer_item, actor=user)
    update_answer(existing, content, actor=user, base=base)
    read_by_acting(user, item, answer_item)
    return answer_item


@transaction.atomic
def add_occurrence(item, *, date, asked_at, people=()):
    """A time the question was asked in the past (the importer), without
    asking anybody: no mails, and no summary later either (summarized
    already: Basecamp mailed it back then; decided 2026-11-22). Returns the
    occurrence, which exists already for the date when it was added
    before."""
    question = Question.objects.get(item=item)
    occurrence, was_created = Occurrence.objects.get_or_create(
        question=question,
        date=date,
        defaults={"asked_at": asked_at, "summarized_at": asked_at},
    )
    if was_created:
        occurrence.asked.set(people)
    return occurrence


def create_answer(question_item, user, content, occurrence):
    item = items_ops.create_item(
        project=question_item.project,
        parent=question_item,
        kind=Kind.ANSWER,
        title=question_item.title,
        creator=user,
        position=0,  # Answers are ordered by date
    )
    Answer.objects.create(
        item=item, content=content, occurrence=occurrence, author=user
    )
    attachments.link(item, content, actor=user)
    event = items_ops.created(item, user)
    mentions.update(item, content, actor=user, event=event)
    return item


@transaction.atomic
def update_answer(answer, content, *, actor, base=None):
    """``base``: see ``items.operations.update_todo()``"""
    item = answer.item
    answer = Answer.objects.select_for_update().select_related("item").get(pk=answer.pk)
    editing.check_base(item, base, actor=actor)
    editing.stop(item, actor)
    if content == answer.content:
        return
    previous = answer.content
    answer.content = content
    answer.save(update_fields=["content"])
    item.updated_at = timezone.now()
    item.save(update_fields=["updated_at"])
    attachments.link(item, content, actor=actor)
    event = record(actor=actor, action=Action.EDITED, project=item.project, item=item)
    mentions.update(item, content, actor=actor, event=event, previous=previous)
    read_by_acting(actor, item)


@transaction.atomic
def set_mail_mode(item, *, user, mode):
    """How the person hears about answers; choosing a mail subscribes
    them"""
    mode = Mode(mode)
    QuestionMail.objects.update_or_create(
        question=item.question, user=user, defaults={"mode": mode}
    )
    if mode != Mode.NONE:
        subscribe(user, item)
    return mode


def due(user, *, project=None):
    """The latest occurrences of questions the person was asked and
    hasn't answered, newest first: "due"."""
    visible = Item.objects.visible_to(user).filter(
        kind=Kind.QUESTION,
        status=Status.ACTIVE,
        project__archived_at__isnull=True,
        project__is_template=False,
    )
    if project is not None:
        visible = visible.filter(project=project)
    occurrences = (
        Occurrence.objects
        .filter(
            question__item__in=visible,
            question__paused_at__isnull=True,
            question__people=user,
            asked=user,
        )
        .annotate(
            has_newer=Exists(_newer()),
            answered=Exists(
                Answer.objects.filter(
                    occurrence=OuterRef("pk"), author=user
                ).not_trashed()
            ),
        )
        .filter(has_newer=False, answered=False)
        .select_related("question__item__project")
        .order_by("-asked_at", "-pk")
    )
    return list(occurrences)
