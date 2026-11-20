"""Pages of check-ins (specs/checkins.md)"""

import datetime as dt
import zoneinfo

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak import schedules
from biwak.accounts.models import User
from biwak.activity.operations import is_subscribed
from biwak.checkins import operations as ops
from biwak.checkins.models import Answer, Mode, Occurrence, mail_mode
from biwak.forms import Form
from biwak.items import operations as item_ops
from biwak.items.models import Comment, Item, Kind
from biwak.items.views import CommentForm, item_for
from biwak.projects.views import project_for


# How many occurrences a page shows (older ones: "Show more")
OCCURRENCES_PER_PAGE = 5

TIME_ZONES = sorted(zoneinfo.available_timezones())


def question_for(request, pk):
    """The question's item if the person sees it, else 404"""
    return item_for(request, pk, Kind.QUESTION)


def staff_only(request):
    if request.user.is_client:
        raise PermissionDenied


def candidate_people(project):
    """Who a question of the project can ask: members, and all staff in
    all-access projects (clients only on visible questions, checked by
    ``operations.set_people()``)"""
    people = Q(memberships__project=project)
    if project.is_all_access:
        people |= Q(is_client=False)
    return User.objects.active().filter(people).distinct()


# Forms -----------------------------------------------------------------------


class QuestionForm(Form):
    title = forms.CharField(label=_("Question"), max_length=500)
    repeat = forms.ChoiceField(
        label=_("Asked"),
        choices=[c for c in schedules.preset_choices() if c[0]],
        initial="weekly",
    )
    custom_rule = forms.CharField(
        label=_("Custom schedule"),
        required=False,
        max_length=200,
        help_text=_("An RRULE, e.g. FREQ=WEEKLY;BYDAY=MO,TH"),
    )
    starts_on = forms.DateField(
        label=_("First asked on"),
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text=_("Weekly and monthly schedules count from this date."),
    )
    time_of_day = forms.TimeField(
        label=_("Time of day"), widget=forms.TimeInput(attrs={"type": "time"})
    )
    time_zone = forms.ChoiceField(
        label=_("Time zone"),
        choices=[(name, name) for name in TIME_ZONES],
        initial=settings.TIME_ZONE,
    )
    people = forms.ModelMultipleChoiceField(
        label=_("People asked"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)
    field_order = [
        "title",
        "repeat",
        "custom_rule",
        "starts_on",
        "time_of_day",
        "time_zone",
        "people",
        "visible",
    ]

    def __init__(self, *args, project, item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        self.fields["people"].queryset = candidate_people(project)
        if item is not None:
            # The switch is on the page
            del self.fields["visible"]

    def _rule(self, data):
        if data.get("repeat") == schedules.CUSTOM:
            if not data.get("custom_rule"):
                raise schedules.InvalidRule(_("Enter the schedule."))
            return schedules.validate(data["custom_rule"])
        if data.get("repeat") and data.get("starts_on"):
            return schedules.from_preset(data["repeat"], data["starts_on"])
        return ""

    def clean(self):
        data = super().clean()
        repeat = data.get("repeat")
        field = "custom_rule" if repeat == schedules.CUSTOM else "repeat"
        try:
            data["rule"] = self._rule(data)
        except schedules.InvalidRule as exc:
            data["rule"] = ""
            self.add_error(field, str(exc))
        visible = (
            self.item.is_client_visible
            if self.item is not None
            else data.get("visible", False)
        )
        if not visible and any(u.is_client for u in data.get("people", [])):
            self.add_error(
                "people", _("Clients can only be asked about check-ins they can see.")
            )
        return data


class AnswerForm(Form):
    content = forms.CharField(
        label=_("Your answer"), widget=forms.Textarea(attrs={"rows": 6})
    )


# The project's check-ins -----------------------------------------------------


def project_checkins(request, pk):
    project = project_for(request, pk)
    questions = (
        Item.objects
        .visible_to(request.user)
        .filter(project=project, kind=Kind.QUESTION)
        .select_related("question")
        .order_by("title", "pk")
    )
    due = {o.question_id for o in ops.due(request.user, project=project)}
    return render(
        request,
        "checkins/project_checkins.html",
        {
            "project": project,
            "questions": [(q, q.pk in due) for q in questions],
            "can_manage": not request.user.is_client,
        },
    )


def _form_initial(item):
    question = item.question
    preset = schedules.preset_of(question.rule)
    # A preset only when it gives the rule from the first date; else the
    # form would rebuild it from another weekday or day when saved
    if preset != schedules.CUSTOM and (
        schedules.from_preset(preset, question.starts_on) != question.rule
    ):
        preset = schedules.CUSTOM
    return {
        "title": item.title,
        "repeat": preset,
        "custom_rule": question.rule if preset == schedules.CUSTOM else "",
        "starts_on": question.starts_on,
        "time_of_day": question.time_of_day,
        "time_zone": question.time_zone,
        "people": list(question.people.all()),
    }


def question_new(request, pk):
    staff_only(request)
    project = project_for(request, pk)
    form = QuestionForm(
        request.POST or None,
        project=project,
        initial={"starts_on": dt.date.today(), "people": [request.user]},
    )
    if form.is_valid():
        data = form.cleaned_data
        item = ops.create_question(
            project=project,
            title=data["title"],
            creator=request.user,
            rule=data["rule"],
            starts_on=data["starts_on"],
            time_of_day=data["time_of_day"],
            time_zone=data["time_zone"],
            people=list(data["people"]),
            visible=data["visible"],
        )
        return redirect(item)
    return render(
        request,
        "checkins/question_form.html",
        {"form": form, "project": project, "item": None},
    )


def question_edit(request, pk):
    staff_only(request)
    item = question_for(request, pk)
    form = QuestionForm(
        request.POST or None,
        project=item.project,
        item=item,
        initial=_form_initial(item),
    )
    if form.is_valid():
        data = form.cleaned_data
        ops.update_question(
            item,
            actor=request.user,
            title=data["title"],
            rule=data["rule"],
            starts_on=data["starts_on"],
            time_of_day=data["time_of_day"],
            time_zone=data["time_zone"],
            people=list(data["people"]),
        )
        return redirect(item)
    return render(
        request,
        "checkins/question_form.html",
        {"form": form, "project": item.project, "item": item},
    )


@require_POST
def question_pause(request, pk):
    """Pauses the question, or (``resume``) asks again from the next date"""
    staff_only(request)
    item = question_for(request, pk)
    if request.POST.get("resume"):
        ops.resume(item, actor=request.user)
    else:
        ops.pause(item, actor=request.user)
    return redirect(item)


@require_POST
def question_mail(request, pk):
    item = question_for(request, pk)
    try:
        ops.set_mail_mode(item, user=request.user, mode=request.POST.get("mode"))
    except ValueError:
        raise Http404("Unknown mode") from None
    return redirect(item)


# The question's page ---------------------------------------------------------


def _answers(request, occurrences):
    """The occurrences' answers (the person's visible ones), newest first,
    with their comments, as ``{occurrence ID: [(answer, comments)]}``"""
    visible = Item.objects.visible_to(request.user)
    answers = (
        Answer.objects
        .filter(occurrence__in=occurrences, item__in=visible)
        .select_related("item__creator", "occurrence")
        .order_by("-item__created_at", "-pk")
    )
    comments = {}
    for comment in Comment.objects.filter(
        item__in=[a.item_id for a in answers]
    ).select_related("author"):
        comments.setdefault(comment.item_id, []).append(comment)
    result = {o.pk: [] for o in occurrences}
    for answer in answers:
        result[answer.occurrence_id].append((answer, comments.get(answer.pk, [])))
    return result


def _occurrence_page(item, request):
    """The occurrences to show: the newest first; from ``?before=`` (a date)
    on, or from ``?occurrence=`` on; and where the next page starts"""
    occurrences = Occurrence.objects.filter(question__item=item)
    if before := request.GET.get("before"):
        try:
            occurrences = occurrences.filter(date__lt=dt.date.fromisoformat(before))
        except ValueError as error:
            raise Http404("Bad date") from error
    elif pk := request.GET.get("occurrence"):
        try:
            chosen = get_object_or_404(occurrences, pk=int(pk))
        except ValueError as error:
            raise Http404("Bad occurrence") from error
        occurrences = occurrences.filter(date__lte=chosen.date)
    found = list(occurrences.order_by("-date", "-pk")[: OCCURRENCES_PER_PAGE + 1])
    more = len(found) > OCCURRENCES_PER_PAGE
    found = found[:OCCURRENCES_PER_PAGE]
    return found, found[-1].date.isoformat() if more else None


def question(request, pk):
    item = question_for(request, pk)
    question = item.question
    user = request.user
    occurrences, more = _occurrence_page(item, request)
    answers = _answers(request, occurrences)
    latest = ops.latest_occurrence(item)
    is_latest_page = bool(occurrences) and occurrences[0] == latest
    rows = [(o, answers[o.pk]) for o in occurrences]
    comment_form = CommentForm()
    comment_form.fields["content"].widget.attrs["data-mentions"] = ""
    people = question.people.all()
    if user.is_client:
        # As on the project page: clients know the members
        people = people.filter(memberships__project=item.project)
    people = sorted(people, key=lambda u: (u.full_name or u.email).lower())
    return render(
        request,
        "checkins/question.html",
        {
            "item": item,
            "question": question,
            "rows": rows,
            "more": more,
            "latest": latest,
            "missing": ops.missing(latest) if is_latest_page and latest else [],
            "can_answer": ops.can_answer(user, item),
            "answered": {
                o.pk
                for o in occurrences
                if any(a.author_id == user.pk for a, _c in answers[o.pk])
            },
            "comment_form": comment_form,
            "people": people,
            "mode": mail_mode(user, item),
            "modes": Mode.choices,
            "is_subscribed": is_subscribed(user, item),
            "can_manage": not user.is_client,
            "can_switch": not user.is_client,
            "is_paused": question.is_paused,
        },
    )


def question_person(request, pk, user_pk):
    """One person's answers over time, newest first, ``?before=`` a date"""
    item = question_for(request, pk)
    person = get_object_or_404(User, pk=user_pk)
    asked = item.question.people.filter(pk=person.pk).exists()
    visible = Item.objects.visible_to(request.user)
    answers = Answer.objects.filter(
        occurrence__question__item=item, author=person, item__in=visible
    ).select_related("item", "occurrence")
    if not asked and not answers.exists():
        raise Http404("Not asked")
    if before := request.GET.get("before"):
        try:
            answers = answers.filter(occurrence__date__lt=dt.date.fromisoformat(before))
        except ValueError as error:
            raise Http404("Bad date") from error
    found = list(
        answers.order_by("-occurrence__date", "-pk")[: OCCURRENCES_PER_PAGE + 1]
    )
    more = len(found) > OCCURRENCES_PER_PAGE
    found = found[:OCCURRENCES_PER_PAGE]
    return render(
        request,
        "checkins/person.html",
        {
            "item": item,
            "person": person,
            "answers": found,
            "more": found[-1].occurrence.date.isoformat() if more else None,
        },
    )


# Answering -------------------------------------------------------------------


def _chosen_occurrence(request, item):
    """``?occurrence=``, else the latest; 404 for none or one of another
    question"""
    if pk := request.GET.get("occurrence") or request.POST.get("occurrence"):
        try:
            return get_object_or_404(
                Occurrence.objects.filter(question__item=item), pk=int(pk)
            )
        except ValueError as error:
            raise Http404("Bad occurrence") from error
    if (latest := ops.latest_occurrence(item)) is None:
        raise Http404("Not asked yet")
    return latest


def question_answer(request, pk):
    """The answer form of the latest occurrence, or ``?occurrence=``;
    shows the person's answer if they gave one, to change it"""
    item = question_for(request, pk)
    if not ops.can_answer(request.user, item):
        raise PermissionDenied
    occurrence = _chosen_occurrence(request, item)
    existing = (
        Answer.objects
        .filter(occurrence=occurrence, author=request.user)
        .exclude(item__status="trashed")
        .first()
    )
    form = AnswerForm(
        request.POST or None,
        initial={"content": existing.content if existing else ""},
    )
    form.fields["content"].widget.attrs["data-mentions"] = reverse(
        "mentionable", args=[item.pk]
    )
    if form.is_valid():
        answer = ops.answer(
            item,
            user=request.user,
            content=form.cleaned_data["content"],
            occurrence=occurrence,
        )
        return redirect(answer)
    return render(
        request,
        "checkins/answer.html",
        {
            "item": item,
            "occurrence": occurrence,
            "existing": existing,
            "form": form,
            "skipped": occurrence.skips.filter(user=request.user).exists(),
        },
    )


@require_POST
def question_skip(request, pk):
    item = question_for(request, pk)
    if not ops.can_answer(request.user, item):
        raise PermissionDenied
    occurrence = _chosen_occurrence(request, item)
    try:
        ops.skip(item, user=request.user, occurrence=occurrence)
    except ValueError:
        messages.error(request, _("You answered already."))
        return redirect(item)
    messages.success(request, _("Skipped this time."))
    return redirect(item)


@require_POST
def answer_comment(request, pk):
    """A comment on an answer, from the question's page"""
    answer_item = item_for(request, pk, Kind.ANSWER)
    form = CommentForm(request.POST)
    if form.is_valid():
        item_ops.add_comment(
            answer_item, author=request.user, content=form.cleaned_data["content"]
        )
    return redirect(answer_item)
