"""Check-ins (specs/checkins.md): questions, their occurrences with the
answers, answering and the mail mode. The same operations as the
web interface."""

import datetime as dt
from typing import Literal

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak import schedules
from biwak.accounts.models import User
from biwak.activity.mentions import resolve as resolve_mentions
from biwak.api_conventions import (
    ItemOut,
    PersonOut,
    Title,
    absolute,
    html,
    item_out,
    page_of,
    paginated,
    person_out,
)
from biwak.checkins import operations as ops, schedule
from biwak.checkins.models import Answer, Occurrence, mail_mode
from biwak.items.api import item_for as any_item_for
from biwak.items.models import Item, Kind
from biwak.projects.api import project_for
from biwak.reactions.models import Reaction
from biwak.reactions.schemas import ReactionOut, reactions_out


router = Router(tags=["check-ins"])


def bad_request(message):
    raise HttpError(400, message)


def staff_only(request):
    """After looking up what's changed: a client gets 404 for what they
    don't see, not 403"""
    if request.user.is_client:
        raise HttpError(403, _("Only staff can change check-ins."))


def question_for(request, pk):
    return any_item_for(request, pk, Kind.QUESTION)


def _rule(value, anchor):
    """A preset name (counting from the first date) or an RRULE as a valid
    rule; 400 for anything else"""
    try:
        return schedules.resolve(value, anchor)
    except schedules.InvalidRule as exc:
        bad_request(str(exc))


def _zone(name):
    try:
        return schedule.zone(name).key
    except ValueError as exc:
        bad_request(str(exc))


# Questions --------------------------------------------------------------------


class QuestionOut(ItemOut):
    rule: str
    schedule_description: str
    starts_on: dt.date
    time_of_day: dt.time
    time_zone: str
    people: list[PersonOut]
    paused: bool
    next_at: dt.datetime | None
    latest_occurrence_id: int | None
    mail: Literal["each", "summary", "none"]


def question_out(request, item):
    question = item.question
    latest = ops.latest_occurrence(item)
    return item_out(item) | {
        "rule": question.rule,
        "schedule_description": question.schedule_description,
        "starts_on": question.starts_on,
        "time_of_day": question.time_of_day,
        "time_zone": question.time_zone,
        # Clients only learn about the project's members
        "people": [
            person_out(user)
            for user in item.project.people_known_to(
                request.user, question.people.all()
            )
        ],
        "paused": question.is_paused,
        "next_at": question.next_at,
        "latest_occurrence_id": latest.pk if latest else None,
        "mail": str(mail_mode(request.user, item)),
    }


@router.get("projects/{project_id}/checkins/", response=list[QuestionOut])
def question_list(request, project_id: int):
    project = project_for(request, project_id)
    questions = (
        Item.objects
        .visible_to(request.user)
        .filter(project=project, kind=Kind.QUESTION)
        .select_related("creator", "question")
        .prefetch_related("question__people")
        .order_by("title", "pk")
    )
    return [question_out(request, item) for item in questions]


class QuestionIn(Schema):
    title: Title
    schedule: str
    time_of_day: dt.time
    starts_on: dt.date | None = None
    time_zone: str | None = None
    people: list[int] = []
    visible_to_clients: bool = False


def _people(ids):
    people = list(User.objects.active().filter(pk__in=ids))
    if len(people) != len(set(ids)):
        bad_request(_("Some of these people don't exist."))
    return people


@router.post("projects/{project_id}/checkins/", response={201: QuestionOut})
def question_create(request, project_id: int, data: QuestionIn):
    """Staff only. ``schedule`` is a preset (weekdays, weekly, biweekly,
    monthly, monthly-first, monthly-last, quarterly, yearly: counting from
    ``starts_on``, default today) or an RRULE (at most daily), asked at
    ``time_of_day`` in ``time_zone`` (default: the installation's)."""
    project = project_for(request, project_id)
    staff_only(request)
    starts_on = data.starts_on or schedules.today()
    try:
        item = ops.create_question(
            project=project,
            title=data.title,
            creator=request.user,
            rule=_rule(data.schedule, starts_on),
            starts_on=starts_on,
            time_of_day=data.time_of_day,
            time_zone=_zone(data.time_zone) if data.time_zone else None,
            people=_people(data.people),
            visible=data.visible_to_clients,
        )
    except ValueError as exc:
        bad_request(str(exc))
    return Status(201, question_out(request, question_for(request, item.pk)))


@router.get("checkins/{question_id}/", response=QuestionOut)
def question_detail(request, question_id: int):
    return question_out(request, question_for(request, question_id))


class QuestionPatch(Schema):
    title: Title | None = None
    schedule: str | None = None
    starts_on: dt.date | None = None
    time_of_day: dt.time | None = None
    time_zone: str | None = None
    people: list[int] | None = None
    paused: bool | None = None


@router.patch("checkins/{question_id}/", response=QuestionOut)
def question_update(request, question_id: int, data: QuestionPatch):
    """Staff only. Changes the fields given; ``people`` is the complete new
    set; ``paused`` pauses or resumes. A new schedule counts from now."""
    item = question_for(request, question_id)
    staff_only(request)
    given = data.model_fields_set
    changes = {}
    # ``"people": []`` asks nobody; null is a mistake, as for the others
    for field in [
        "title",
        "starts_on",
        "time_of_day",
        "time_zone",
        "schedule",
        "people",
    ]:
        if field in given:
            value = getattr(data, field)
            if value in (None, ""):
                bad_request(_("Leave out what doesn't change instead of sending null."))
            changes[field] = value
    if "schedule" in changes:
        anchor = changes.get("starts_on", item.question.starts_on)
        changes["rule"] = _rule(changes.pop("schedule"), anchor)
    if "time_zone" in changes:
        changes["time_zone"] = _zone(changes["time_zone"])
    if "people" in changes:
        changes["people"] = _people(changes["people"])
    try:
        ops.update_question(item, actor=request.user, **changes)
        if data.paused is not None:
            (ops.pause if data.paused else ops.resume)(item, actor=request.user)
    except ValueError as exc:
        bad_request(str(exc))
    return question_out(request, question_for(request, question_id))


# Occurrences and answers ------------------------------------------------------


class AnswerOut(ItemOut):
    occurrence_id: int
    author: PersonOut
    content: str
    content_html: str
    reactions: list[ReactionOut]


def answer_out(answer, user):
    item = answer.item
    return item_out(item) | {
        "occurrence_id": answer.occurrence_id,
        "author": person_out(answer.author),
        "content": answer.content,
        "content_html": html(answer.content, item),
        "reactions": reactions_out(item, None, user),
    }


class OccurrenceOut(Schema):
    id: int
    question_id: int
    date: dt.date
    asked_at: dt.datetime
    answers: list[AnswerOut]
    # Those asked who haven't answered; only for the latest
    # occurrence
    missing: list[PersonOut] | None


@router.get("checkins/{question_id}/occurrences/", response=page_of(OccurrenceOut))
def occurrence_list(
    request,
    question_id: int,
    person_id: int | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """The question's occurrences with their answers (newest first, as on
    the page), the latest first; ``person_id``: only that person's answers
    (and the occurrences they answered)"""
    item = question_for(request, question_id)
    latest = ops.latest_occurrence(item)
    visible = Item.objects.visible_to(request.user)
    occurrences = Occurrence.objects.filter(question__item=item)
    answers = Answer.objects.filter(item__in=visible)
    if person_id is not None:
        answers = answers.filter(author=person_id)
        occurrences = occurrences.filter(answers__in=answers).distinct()

    def out(occurrence):
        found = (
            answers
            .filter(occurrence=occurrence)
            .select_related("item__creator", "author")
            .prefetch_related(
                Prefetch(
                    "item__reactions",
                    queryset=Reaction.objects.select_related("user"),
                )
            )
            .order_by("-item__created_at", "-pk")
        )
        return {
            "id": occurrence.pk,
            "question_id": item.pk,
            "date": occurrence.date,
            "asked_at": occurrence.asked_at,
            "answers": [answer_out(a, request.user) for a in found],
            "missing": (
                [
                    person_out(u)
                    for u in item.project.people_known_to(
                        request.user, ops.missing(occurrence)
                    )
                ]
                if occurrence == latest
                else None
            ),
        }

    return paginated(
        request,
        occurrences,
        out,
        ordering=("-date", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )


def _occurrence(item, occurrence_id):
    if occurrence_id is None:
        return None
    return get_object_or_404(Occurrence, pk=occurrence_id, question__item=item)


class AnswerIn(Schema):
    content: str
    occurrence_id: int | None = None


@router.post("checkins/{question_id}/answer/", response=AnswerOut)
def answer_create(request, question_id: int, data: AnswerIn):
    """Your answer to the occurrence (default: the latest), or the change
    of the one you gave; you answer once per occurrence. Only for people
    asked."""
    item = question_for(request, question_id)
    if not data.content.strip():
        bad_request(_("The answer is empty."))
    if not ops.can_answer(request.user, item):
        raise HttpError(403, _("You aren't asked this question."))
    occurrence = _occurrence(item, data.occurrence_id)
    try:
        answer = ops.answer(
            item,
            user=request.user,
            content=resolve_mentions(item, data.content, author=request.user),
            occurrence=occurrence,
        )
    except ValueError as exc:
        bad_request(str(exc))
    return answer_out(
        Answer.objects.select_related("item__creator", "author").get(item=answer),
        request.user,
    )


class MailOut(Schema):
    question_id: int
    mode: Literal["each", "summary", "none"]


class MailIn(Schema):
    mode: Literal["each", "summary", "none"]


@router.get("checkins/{question_id}/mail/", response=MailOut)
def mail_detail(request, question_id: int):
    item = question_for(request, question_id)
    return {"question_id": item.pk, "mode": str(mail_mode(request.user, item))}


@router.put("checkins/{question_id}/mail/", response=MailOut)
def mail_update(request, question_id: int, data: MailIn):
    """How you hear about the answers: a mail each, a summary the morning
    after (the default) or none"""
    item = question_for(request, question_id)
    mode = ops.set_mail_mode(item, user=request.user, mode=data.mode)
    return {"question_id": item.pk, "mode": str(mode)}


class DueOut(Schema):
    question_id: int
    title: str
    project_id: int
    project_name: str
    occurrence_id: int
    date: dt.date
    asked_at: dt.datetime
    url: str
    visible_to_clients: bool


@router.get("me/checkins/due/", response=list[DueOut])
def due(request, project_id: int | None = None):
    """The latest occurrences of the questions you're asked and haven't
    answered, across projects (or of ``project_id``)"""
    project = project_for(request, project_id) if project_id is not None else None
    return [
        {
            "question_id": occurrence.question.item_id,
            "title": occurrence.question.item.title,
            "project_id": occurrence.question.item.project_id,
            "project_name": occurrence.question.item.project.name,
            "occurrence_id": occurrence.pk,
            "date": occurrence.date,
            "asked_at": occurrence.asked_at,
            "url": absolute(
                reverse("question_answer", args=[occurrence.question.item_id])
            )
            + f"?occurrence={occurrence.pk}",
            "visible_to_clients": occurrence.question.item.is_client_visible,
        }
        for occurrence in ops.due(request.user, project=project)
    ]
