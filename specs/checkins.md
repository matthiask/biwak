# Check-ins

A question asked automatically on a schedule to chosen people, answers
collected in one place with comments: "How are you, what are you working
on this week?", "Read any good books lately?". Used heavily for the team
itself, less for client projects.

**Status:** open.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`; have the scheduling tests reviewed.

**Depends on:** schedules (`todos.md`, stage 1), mails and mentions
(`notifications.md`, stage 1), attachments (`files.md`, stage 1).
Answering by mail comes with `notifications.md`, stage 2, built after
this part.

## Model

- **Kind `question`** (parent: none), switchable, not commentable:
  `Question(Detail)` with the question as the item's title, `rule` (an
  RRULE, `biwak/schedules.py`), `time_of_day`, `time_zone` (default
  `TIME_ZONE`), `people` (many-to-many: who is asked), `paused_at`,
  `remind_after` (hours, default 24, decided 2026-11-20; empty for no
  reminder).
- **`Occurrence(question, asked_at, reminded_at)`**: one per time the
  question is asked.
- **Kind `answer`** (parent: its question), commentable:
  `Answer(Detail)` with `content` (Markdown) and `occurrence`; one per
  person and occurrence (unique on occurrence and creator), editable by
  its author.
- **`Skip(occurrence, user)`**: someone skipped an occurrence.
- **`QuestionMail(question, user, mode)`**: how a person hears about the
  answers: `each` (a mail per answer, through the normal notifications),
  `summary` (one mail the morning after an occurrence with all its
  answers; the default, decided 2026-11-20: ten mails per question are
  too many) or `none`.

## Behaviour

- **Asking:** `./manage.py send_mails` (every minute, `notifications.md`)
  also creates the occurrences that are due (`schedules.next_date()` with
  the time of day in the question's time zone) and mails the question
  to its people. Paused questions aren't asked; resuming doesn't ask the
  missed occurrences.
- **The question mail** links to the answer form; in stage 2 of
  `notifications.md`, replying to it posts the answer.
- **Answering** in the app: `/questions/<pk>/answer/` for the latest
  occurrence (or `?occurrence=` for an older one), Markdown with
  mentions and attachments. Everybody asked is subscribed to the
  question.
- **Skipping:** a "Skip this time" button next to the form.
- **Reminder:** once, `remind_after` hours after asking, to the people
  who neither answered nor skipped.
- **Answers' mails** per `QuestionMail`: `each` through `notify()`;
  `summary` at 07:00 the morning after the occurrence (in `send_mails`),
  one mail with all answers.
- Staff create and edit questions; clients can be asked when the
  question is visible to clients.

## Pages

- `/projects/<pk>/checkins/`: the project's questions with their
  schedule (`schedules.describe()`), next date and whether paused.
- `/questions/<pk>/`: the latest occurrence's answers (newest first) and
  who hasn't answered yet; older occurrences below, paginated by date;
  each answer with its comments.
- `/questions/<pk>/people/<user pk>/`: a person's answers over time.
- New and edit forms for questions (staff); pause and resume.
- The person's open questions ("due") on the project page.

## API and CLI

Endpoints for questions (list, create, update, pause), occurrences with
answers (cursor-paginated), answering, skipping, the mail mode.
`biwak checkins PROJECT`, `biwak checkin show QUESTION`,
`biwak checkin answer QUESTION [TEXT]` (standard input like comments),
`biwak checkin due` (what I haven't answered yet).

## Done when

Pages, API and CLI for all of the above. Tests: schedules across
daylight saving time changes and time zones (a question at 09:00
Europe/Zurich stays at 09:00 local time in March and October), pausing
and resuming, answering an older occurrence, one answer per person and
occurrence, reminders only to those who neither answered nor skipped,
the summary mail, a client asked on a visible question and not seeing
internal questions.
