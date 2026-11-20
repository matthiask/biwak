# Check-ins

A question asked automatically on a schedule to chosen people, answers
collected in one place with comments: "How are you, what are you working
on this week?", "Read any good books lately?". Used heavily for the team
itself, less for client projects.

**Status:** built (2026-11-20): models, `biwak/checkins/` (`schedule.py`
the time arithmetic, `operations.py` asking, reminding, summaries and
answering, `mails.py`), pages, API (`checkins/`), CLI 0.12.0. Decisions
made while building, to be confirmed (marked "Open" where the spec left a
value or a product choice to the builder):

- **Added to the model:** `Question.starts_on` (the date the rule counts
  from: first date and phase of "every two weeks"; the forms say "first
  asked on"), `Question.next_at` (stored: when it is asked next, computed
  from rule, time of day and time zone whenever one changes and after
  asking; empty while paused), `Occurrence.date` (the scheduled date in the
  question's time zone, unique per question: editing the schedule on the
  day never asks a date twice), `Occurrence.asked` (whom it was asked: who
  is missing is judged against these, not against today's people),
  `Occurrence.summarized_at`, `Answer.author` (the item's creator repeated
  for the unique constraint). The audit log covers the tables people change
  (not `Occurrence`, not `next_at`).
- **Time of day:** 09:00 stays 09:00 on the wall clock in the question's
  zone, so in UTC it moves by an hour at the changes. A time which doesn't
  exist (02:30 when the clocks go forward) is asked an hour later (03:30);
  one which happens twice (02:30 when they go back) once, the first time.
  A date is the calendar date in the question's zone. An occurrence's date
  is the rule's date, not the date of the moment it is asked: a time in a
  gap just before midnight (23:30 when America/Nuuk goes from 23:00 to
  00:00) is asked at 00:30 the next day, for the day before (fixed
  2026-11-20: it was stored under the next day, which then wasn't asked).
- **After downtime** (or a late run) a question is asked once, for the
  latest date due, not for every missed date; `asked_at` is when it was
  really asked.
- **Pausing** clears `next_at`; resuming computes it from now, so missed
  occurrences aren't asked. A reminder which comes due while the question
  can't be asked (paused, trashed, archived or in an archived project) is
  dropped, not sent when it comes back; such questions also move on
  without asking.
- **Editing the schedule** counts from now: today's time only if still
  ahead, and a date already asked isn't asked again.
- **People:** adding is from the next occurrence on (those added are
  subscribed and can answer the latest occurrence, but aren't in its
  `asked`, aren't reminded and aren't "due" for it); removing unsubscribes
  and keeps their answers. Clients only when the question is visible to
  clients; if it turns internal they aren't asked or mailed (they stay in
  the list). Only people in the list answer or skip (staff who aren't asked
  don't), the author edits their own answer (answering again changes it,
  also from the trash), answering takes back a skip, skipping after
  answering is refused.
- **Reminder:** `remind_after` hours (elapsed hours, not wall clock) after
  `asked_at`, once, only for the latest occurrence of the question (when
  the next is asked first, as for a daily question reminded after 24 hours,
  the older one is history) and only for people asked then who still are in
  the list.
- **Summary:** 07:00 on the day after the occurrence's date in the
  question's time zone (Open: or the installation's, like the digest), to
  subscribers whose mode is `summary` (the default) who see the question and
  whose level isn't "nothing"; no mail for an occurrence without answers;
  answers after it are not sent; choosing a mode other than `none`
  subscribes.
- **Answers' mails** (`each`) go through the normal notifications:
  everybody else gets nothing per answer (unless mentioned); `each` passes
  the level "concerns me".
- **Not asked:** trashed and archived questions, questions of archived
  projects.
- **Mails** (question, reminder, summary) go out after the commit, one per
  person, in their language; a mail which can't be sent is logged and not
  retried. Replying by mail (`notifications.md`, stage 2) goes into
  `biwak/checkins/mails.py`: `reply_headers()` returns the `Reply-To` and
  `thread()` the thread of a person and occurrence; `Occurrence` is what a
  reply points at.
- **Open (values the spec doesn't fix):** how many occurrences a page shows
  (5, `OCCURRENCES_PER_PAGE`); the wording of the three mails and the
  pages; no default time of day (the form asks); asking people with the
  level "nothing" (they are asked and reminded regardless).

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
  each answer with its comments. `?occurrence=` starts the list at that
  occurrence, `?before=` (a date) at the next older page.
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
