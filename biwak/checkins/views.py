"""Pages of check-ins (specs/checkins.md)"""

import datetime as dt
import zoneinfo

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.accounts.models import User
from biwak.activity.notify import people_who_see
from biwak.activity.operations import is_subscribed
from biwak.checkins import operations as ops
from biwak.checkins.models import Answer, Mode, Occurrence, mail_mode
from biwak.forms import Form
from biwak.items import operations as item_ops
from biwak.items.models import Comment, Item, Kind
from biwak.items.views import CommentForm, item_for
from biwak.projects.views import project_for
from biwak.reactions.operations import prefetch
from biwak.schedules_forms import KEEP, RuleField, RuleFormMixin


# How many occurrences a page shows (older ones: "Show more")
OCCURRENCES_PER_PAGE = 5

TIME_ZONES = sorted(zoneinfo.available_timezones())


def question_for(request, pk):
    """The question's item if the person sees it, else 404"""
    return item_for(request, pk, Kind.QUESTION)


def staff_only(request):
    if request.user.is_client:
        raise PermissionDenied


# Forms -----------------------------------------------------------------------


class QuestionForm(RuleFormMixin, Form):
    title = forms.CharField(label=_("Question"), max_length=500)
    rule = RuleField(label=_("Asked"), allow_empty=False, default_frequency="weekly")
    starts_on = forms.DateField(
        label=_("First asked on"),
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text=_("Schedules every two weeks and more count from this date."),
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
        "rule",
        "starts_on",
        "time_of_day",
        "time_zone",
        "people",
        "visible",
    ]

    def __init__(self, *args, project, item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        self.fields["rule"].widget.anchor = self.initial.get("starts_on")
        # Who sees a visible question: clients only on visible ones, checked
        # by ``clean()`` and ``operations.set_people()``
        self.fields["people"].queryset = people_who_see(project, visible=True)
        if item is not None:
            # The switch is on the page
            del self.fields["visible"]

    def clean(self):
        data = super().clean()
        if data.get("rule") is KEEP:
            data["rule"] = self.initial.get("rule", "")
        visible = (
            self.item.is_client_visible
            if self.item is not None
            else data.get("visible", False)
        )
        # Clients already in the list stay when the question turned internal
        kept = set(self.item.question.people.all()) if self.item else set()
        if not visible and any(
            u.is_client and u not in kept for u in data.get("people", [])
        ):
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
            "any_paused": any(q.question.is_paused for q in questions),
        },
    )


@require_POST
def project_checkins_resume(request, pk):
    """Asks all the project's paused check-ins again (staff)"""
    project = project_for(request, pk)
    staff_only(request)
    ops.resume_all(project, actor=request.user)
    return redirect("project_checkins", project.pk)


def _form_initial(item):
    question = item.question
    return {
        "title": item.title,
        "rule": question.rule,
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


def _comment_form(answer):
    """The comment form under an answer: own field IDs, and the people to
    mention come from the answer"""
    form = CommentForm(auto_id=f"id_answer_{answer.pk}_%s")
    form.fields["content"].widget.attrs["data-mentions"] = reverse(
        "mentionable", args=[answer.pk]
    )
    return form


def _answers(request, occurrences):
    """The occurrences' answers (the person's visible ones), newest first,
    with their comments and a comment form, as ``{occurrence ID: [(answer,
    comments, form)]}``"""
    visible = Item.objects.visible_to(request.user)
    answers = (
        Answer.objects
        .filter(occurrence__in=occurrences, item__in=visible)
        .select_related("item__creator", "occurrence", "author")
        .order_by("-item__created_at", "-pk")
    )
    comments = {}
    for comment in Comment.objects.filter(
        item__in=[a.item_id for a in answers]
    ).select_related("author"):
        comments.setdefault(comment.item_id, []).append(comment)
    prefetch(*[answer.item for answer in answers])
    result = {o.pk: [] for o in occurrences}
    for answer in answers:
        result[answer.occurrence_id].append((
            answer,
            comments.get(answer.pk, []),
            _comment_form(answer),
        ))
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
    people = sorted(
        item.project.people_known_to(user, question.people.all()),
        key=lambda u: (u.full_name or u.email).lower(),
    )
    missing = ops.missing(latest) if is_latest_page and latest else []
    return render(
        request,
        "checkins/question.html",
        {
            "item": item,
            "question": question,
            "rows": rows,
            "more": more,
            "latest": latest,
            "missing": item.project.people_known_to(user, missing),
            "can_answer": ops.can_answer(user, item),
            "answered": {
                o.pk
                for o in occurrences
                if any(a.author_id == user.pk for a, _c, _f in answers[o.pk])
            },
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
    """One person's answers over time, newest first, ``?before=`` a date;
    clients only of the project's members"""
    item = question_for(request, pk)
    person = get_object_or_404(User, pk=user_pk)
    if not item.project.people_known_to(request.user, [person]):
        raise Http404("Not a member")
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
        .not_trashed()
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
        },
    )


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
