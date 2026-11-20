"""Check-ins: questions asked on a schedule (specs/checkins.md)

A question is an item (kind ``question``, top level, with the visibility
switch); each time it is asked is an ``Occurrence``; an answer is an item
below the question (kind ``answer``) belonging to one occurrence and one
person.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Detail, Item, Status


def default_time_zone():
    return settings.TIME_ZONE


# Hours after asking (decided 2026-11-20), None: no reminder
DEFAULT_REMIND_AFTER = 24


class Question(Detail):
    """The question itself is the item's title"""

    # An RRULE (biwak.schedules), at most daily
    rule = models.CharField(_("schedule"), max_length=200)
    # The date the rule counts from: the first date it can ask, and the
    # phase of "every two weeks"
    starts_on = models.DateField(_("first asked on"))
    time_of_day = models.TimeField(_("time of day"))
    time_zone = models.CharField(
        _("time zone"), max_length=64, default=default_time_zone
    )
    people = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="questions_asked",
        verbose_name=_("people"),
    )
    paused_at = models.DateTimeField(_("paused at"), null=True, blank=True)
    remind_after = models.PositiveIntegerField(
        _("remind after (hours)"),
        null=True,
        blank=True,
        default=DEFAULT_REMIND_AFTER,
        help_text=_("Empty: no reminder."),
    )
    # When the question is asked next: derived from the rule, the time of
    # day and the time zone whenever one of them changes, or after asking;
    # empty while paused (``biwak.checkins.schedule``)
    next_at = models.DateTimeField(_("asked next at"), null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["next_at"],
                condition=models.Q(next_at__isnull=False),
                name="question_next_at",
            )
        ]
        verbose_name = _("check-in question")
        verbose_name_plural = _("check-in questions")

    @property
    def is_paused(self):
        return self.paused_at is not None

    @property
    def schedule_description(self):
        from biwak import schedules

        return schedules.describe(self.rule)

    @property
    def is_askable(self):
        """Paused, trashed and archived questions and those of archived
        projects aren't asked"""
        item = self.item
        return (
            self.paused_at is None
            and item.status == Status.ACTIVE
            and item.project.archived_at is None
        )


class Occurrence(models.Model):
    """One time a question is asked. ``date`` is the scheduled date in the
    question's time zone: one occurrence per question and date, however
    often the schedule is edited on that day."""

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="occurrences",
        verbose_name=_("question"),
    )
    date = models.DateField(_("date"))
    asked_at = models.DateTimeField(_("asked at"), default=timezone.now)
    reminded_at = models.DateTimeField(_("reminded at"), null=True, blank=True)
    # When the summary mail went out (or was found to be of no use)
    summarized_at = models.DateTimeField(_("summarized at"), null=True, blank=True)
    # Whom it was asked: who is still missing is judged against these, not
    # against whoever is asked today
    asked = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="+", verbose_name=_("asked")
    )

    class Meta:
        ordering = ["-date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "date"], name="unique_occurrence_date"
            )
        ]
        verbose_name = _("occurrence")
        verbose_name_plural = _("occurrences")

    def __str__(self):
        return f"{self.question} on {self.date}"


class Answer(Detail):
    content = models.TextField(_("content"), blank=True)
    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.CASCADE,
        related_name="answers",
        verbose_name=_("occurrence"),
    )
    # The item's creator, repeated for the constraint
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("author"),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["occurrence", "author"], name="one_answer_per_occurrence"
            )
        ]
        verbose_name = _("check-in answer")
        verbose_name_plural = _("check-in answers")


class Skip(models.Model):
    """Somebody skipped an occurrence: no reminder"""

    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.CASCADE,
        related_name="skips",
        verbose_name=_("occurrence"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("person"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["occurrence", "user"], name="unique_skip")
        ]
        verbose_name = _("skip")
        verbose_name_plural = _("skips")

    def __str__(self):
        return f"{self.user} skipped {self.occurrence}"


class Mode(models.TextChoices):
    EACH = "each", _("a mail for each answer")
    SUMMARY = "summary", _("one summary the morning after")
    NONE = "none", _("no mails")


DEFAULT_MODE = Mode.SUMMARY


class QuestionMail(models.Model):
    """How a person hears about the answers to a question (decided
    2026-11-20: a summary unless they chose otherwise)"""

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="mail_modes",
        verbose_name=_("question"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("person"),
    )
    mode = models.CharField(_("mails"), max_length=20, choices=Mode)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["question", "user"], name="unique_question_mail"
            )
        ]
        verbose_name = _("question mail")
        verbose_name_plural = _("question mails")

    def __str__(self):
        return f"{self.user}: {self.mode} for {self.question}"


def mail_mode(user, question_item):
    """The person's mode for the question (its item or ID)"""
    pk = question_item.pk if isinstance(question_item, Item) else question_item
    found = (
        QuestionMail.objects
        .filter(question_id=pk, user=user)
        .values_list("mode", flat=True)
        .first()
    )
    return Mode(found) if found else DEFAULT_MODE
