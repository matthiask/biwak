"""Check-ins (specs/checkins.md): creating and changing questions, asking
them on schedule, summarizing, answering. There are no
reminders for missed check-ins (decided 2026-11-20).

Every change goes through here. ``ask_due()`` and ``summarize_due()`` are
what ``./manage.py send_mails`` runs every minute (see ``run()``): nothing
runs in threads or on requests.
"""

import datetime as dt
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from biwak import schedules
from biwak.accounts.models import NotificationLevel, User
from biwak.activity import mentions
from biwak.activity.models import Action, Subscription
from biwak.activity.notify import can_see, effective_level
from biwak.activity.operations import record, subscribe
from biwak.checkins import mails, schedule
from biwak.checkins.models import (
    Answer,
    Mode,
    Occurrence,
    Question,
    QuestionMail,
    mail_mode,
)
from biwak.files import attachments
from biwak.items import operations as items_ops, visibility
from biwak.items.models import Item, Kind, Status


logger = logging.getLogger(__name__)

# The morning after an occurrence the summary goes out at this time, in the
# question's time zone (decided 2026-11-20)
SUMMARY_AT = dt.time(7, 0)

_UNCHANGED = object()


class NotAllowed(Exception):
    """The person isn't asked this question (views and the API answer 403)"""


# Who -------------------------------------------------------------------------


def askable_people(item):
    """People who can be asked: those who can see the question (clients only
    when it is visible to clients)"""
    return mentions.mentionable_people(item)


def can_answer(user, item):
    """People asked who still see the question; staff who aren't asked
    don't answer"""
    return (
        user.is_active
        and Question.objects.filter(item=item, people=user).exists()
        and can_see(user, item)
    )


def _check_people(item, people, *, kept=()):
    """``kept``: people already in the list, who stay when the question
    turns internal (clients aren't asked then, but aren't removed)"""
    allowed = set(askable_people(item).filter(pk__in=[u.pk for u in people]))
    allowed |= {u for u in kept if u.is_client}
    for user in people:
        if user not in allowed:
            raise ValueError(f"{user} can't see {item}")


def _clean_schedule(rule, time_zone):
    return schedules.validate(rule), schedule.zone(time_zone).key


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
    time_zone=None,
    people=(),
    visible=False,
    now=None,
):
    """Asks the first time on or after ``starts_on`` at ``time_of_day``
    (later than ``now``)"""
    rule, time_zone = _clean_schedule(rule, time_zone or settings.TIME_ZONE)
    item = Item(
        project=project,
        kind=Kind.QUESTION,
        title=title,
        creator=creator,
        position=0,
        visible_to_clients=visible,
    )
    item.save()
    visibility.recompute(item)
    _check_people(item, people)
    question = Question.objects.create(
        item=item,
        rule=rule,
        starts_on=starts_on,
        time_of_day=time_of_day,
        time_zone=time_zone,
    )
    question.next_at = schedule.next_fire_of(question, after=now or timezone.now())
    question.save(update_fields=["next_at"])
    subscribe(creator, item)
    record(actor=creator, action=Action.CREATED, project=project, item=item)
    set_people(item, people, actor=creator)
    return item


@transaction.atomic
def set_people(item, people, *, actor):
    """The complete set of people asked. Those added are subscribed (the
    answers' mails per ``QuestionMail``), those removed lose their
    subscription; they are asked from the next occurrence on."""
    question = Question.objects.select_for_update().get(item=item)
    people = list(people)
    old = set(question.people.all())
    _check_people(item, people, kept=old)
    new = set(people)
    question.people.set(new)
    for user in new - old:
        subscribe(user, item, added_by=actor)
    removed = old - new
    Subscription.objects.filter(item=item, user__in=removed).delete()
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
    time_zone=_UNCHANGED,
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
        changed.append("title")
    if rule is not _UNCHANGED:
        rule = schedules.validate(rule)
    if time_zone is not _UNCHANGED:
        time_zone = schedule.zone(time_zone).key
    given = {
        "rule": rule,
        "starts_on": starts_on,
        "time_of_day": time_of_day,
        "time_zone": time_zone,
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


# Asking and summarizing ------------------------------------------------------


def _recipients(question, occurrence=None):
    """Active people asked who can see the question now (a client doesn't
    once it's internal), and, with an ``occurrence``, were asked then"""
    people = question.people.filter(is_active=True)
    if occurrence is not None:
        people = people.filter(pk__in=occurrence.asked.values("pk"))
    return [user for user in people.order_by("pk") if can_see(user, question.item)]


def _answered_ids(occurrence):
    """People who answered (an answer in the trash doesn't count)"""
    answered = Answer.objects.filter(occurrence=occurrence).exclude(
        item__status=Status.TRASHED
    )
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
            date, _fire = schedule.latest_occurrence(
                question, first=question.next_at, now=now
            )
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
    people = _recipients(question)
    occurrence.asked.set(people)
    mails.after_commit(mails.question_mail, occurrence, people)
    return occurrence


def summary_due_at(occurrence):
    """07:00 on the day after the occurrence's date, in the question's time
    zone; after downtime, the day after it was really asked (people can
    answer first)"""
    time_zone = occurrence.question.time_zone
    day = max(occurrence.date, schedule.local_date(occurrence.asked_at, time_zone))
    return schedule.fire_at(day + dt.timedelta(days=1), SUMMARY_AT, time_zone)


def summary_recipients(question):
    """Subscribers of the question who get summaries (the default mode),
    who see it, and whose level isn't "nothing" (they may have changed
    since)"""
    ids = Subscription.objects.filter(item=question.item).values("user")
    people = User.objects.active().filter(pk__in=ids).order_by("pk")
    return [
        user
        for user in people
        if mail_mode(user, question.item) == Mode.SUMMARY
        and can_see(user, question.item)
        and effective_level(user, question.item) != NotificationLevel.NOTHING
    ]


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
                if people:
                    mails.after_commit(mails.summary_mail, occurrence, people)
            done.append(occurrence)
    return done


def run(*, now=None):
    """What ``send_mails`` does about check-ins; returns the counts"""
    now = now or timezone.now()
    return {
        "asked": len(ask_due(now=now)),
        "summarized": len(summarize_due(now=now)),
    }


# Answering -------------------------------------------------------------------


def answers_of(occurrence):
    """The occurrence's answers, newest first, without those in the trash"""
    return list(
        Answer.objects
        .filter(occurrence=occurrence)
        .exclude(item__status=Status.TRASHED)
        .select_related("item__creator")
        .order_by("-item__created_at", "-pk")
    )


def latest_occurrence(item):
    return (
        Occurrence.objects.filter(question__item=item).order_by("-date", "-pk").first()
    )


def _occurrence(item, occurrence):
    """The occurrence to answer: the latest by default"""
    if occurrence is None:
        occurrence = latest_occurrence(item)
        if occurrence is None:
            raise ValueError("The question hasn't been asked yet.")
    elif occurrence.question_id != item.pk:
        raise ValueError("The occurrence belongs to another question.")
    return occurrence


@transaction.atomic
def answer(item, *, user, content, occurrence=None):
    """The person's answer to the occurrence (default: the latest): creates
    it, or changes the one they gave (``Answer`` is unique per occurrence
    and person); answering brings an answer from the trash
    back. ``NotAllowed`` unless they're asked and see the question."""
    if not can_answer(user, item):
        raise NotAllowed(f"{user} isn't asked {item}")
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
        return _create_answer(item, user, content, occurrence)
    answer_item = existing.item
    if answer_item.status == Status.TRASHED:
        items_ops.restore(answer_item, actor=user)
    _update_answer(existing, content, actor=user)
    return answer_item


def _create_answer(question_item, user, content, occurrence):
    item = Item(
        project=question_item.project,
        parent=question_item,
        kind=Kind.ANSWER,
        title=question_item.title,
        creator=user,
    )
    item.save()
    visibility.recompute(item)
    Answer.objects.create(
        item=item, content=content, occurrence=occurrence, author=user
    )
    attachments.link(item, content, actor=user)
    subscribe(user, item)
    event = record(actor=user, action=Action.CREATED, project=item.project, item=item)
    mentions.update(item, content, actor=user, event=event)
    return item


def _update_answer(answer, content, *, actor):
    item = answer.item
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
        kind=Kind.QUESTION, status=Status.ACTIVE, project__archived_at__isnull=True
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
                Answer.objects.filter(occurrence=OuterRef("pk"), author=user).exclude(
                    item__status=Status.TRASHED
                )
            ),
        )
        .filter(has_newer=False, answered=False)
        .select_related("question__item__project")
        .order_by("-asked_at", "-pk")
    )
    return list(occurrences)
