# Check-ins

A question asked automatically on a schedule to chosen people, answers
collected in one place with comments: "How are you, what are you working
on this week?", "Read any good books lately?". Used heavily for the team
itself, less for client projects.

**Status:** built (2026-11-20): models, `biwak/checkins/` (`schedule.py`
the time arithmetic, `operations.py` asking, summaries and answering,
`mails.py`), pages, API (`checkins/`), CLI 0.12.0; reminders removed
again (CLI 0.14.0), skipping removed (CLI 0.16.0). Decisions
made while building, to be confirmed (marked "Open" where the spec left a
value or a product choice to the builder):

- **No reminders for missed check-ins (decided 2026-11-20).** The
  question mail is the only one asking; who hasn't answered shows on the
  question's page and in "due". Removed what was built: `remind_after`,
  `Occurrence.reminded_at`, the reminder mail, the form, API and CLI
  fields (`--remind`).
- **No skipping (decided 2026-11-20).** Without reminders "Skip this time"
  isn't worth having. Removed: `Skip`, the operation, button, page, API
  endpoint and CLI command (`biwak checkin skip`). "Due" and "missing" mean
  not answered. CLIs 0.15 only lose their `skip` command (the other
  commands read no skip field), so `MINIMUM` stays.
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
  occurrences aren't asked. Questions which can't be asked (paused,
  trashed, archived or in an archived project) move on without asking.
- **Editing the schedule** counts from now: today's time only if still
  ahead, and a date already asked isn't asked again. The edit form
  uses the rule widget (`specs/rule-widget.md`): a rule it can't show
  (from the API or the CLI) stays unchanged unless "Replace" is pressed. A new rule or time
  zone on the day it was asked counts from now in the new zone, so a zone
  where that date is still ahead doesn't ask it again and one where its
  time has passed asks the next date. Decided 2026-11-20: changing the
  zone shortly before the question is asked can skip that day (Zurich to
  Tokyo at 08:00 skips that Monday, 09:00 having passed in Tokyo); an
  accepted rare edge case.
- **A first date which doesn't match the rule** (API and CLI rules, e.g.
  Mondays from a Friday): the first date the rule gives on or after it.
  Decided 2026-11-20: "every two weeks" counts its phase from the first
  date's week, so from a Friday the Monday right after isn't asked, the one
  after it is (the first full interval); that's fine as it is.
- **People:** adding is from the next occurrence on (those added are
  subscribed and can answer the latest occurrence, but aren't in its
  `asked` and aren't "due" for it); removing unsubscribes
  and keeps their answers. Clients only when the question is visible to
  clients; if it turns internal they aren't asked or mailed (they stay in
  the list, and saving the form or the API's `people` with them still
  works; only adding clients to an internal question is refused, decided
  2026-11-20). Only people in the list answer (staff who aren't asked
  don't), the author edits their own answer (answering again changes it,
  also from the trash).
- **Summary:** 07:00 on the day after the occurrence's date in the
  question's time zone (Open: or the installation's, like the digest), or,
  when it was asked later than its date (after downtime), on the day after
  it was asked (fixed 2026-11-20: a late run used the summary up before
  anyone could answer), to subscribers whose mode is `summary` (the
  default) who see the question and whose level isn't "nothing"; no mail for an occurrence without answers;
  answers after it are not sent; choosing a mode other than `none`
  subscribes.
- **Answers' mails** (`each`) go through the normal notifications:
  everybody else gets nothing per answer (unless mentioned); `each` passes
  the level "concerns me".
- **Not asked:** trashed and archived questions, questions of archived
  projects.
- **Mails** (question, summary) go out after the commit, one per
  person, in their language, only to people still active and seeing the
  question then (checked again after the commit, like the notification
  mails; fixed 2026-11-20 after the visibility review); a mail which
  can't be sent is logged and not retried. Replying by mail
  (`notifications.md`, stage 2, built 2026-11-20): `reply_headers()` in
  `biwak/checkins/mails.py` gives the question mail a `Reply-To` whose
  token points at the occurrence; replying answers that occurrence
  (changing an answer given already). The summary has no `Reply-To`.
- **Open (values the spec doesn't fix):** how many occurrences a page shows
  (5, `OCCURRENCES_PER_PAGE`); the wording of the two mails and the
  pages; no default time of day (the form asks); asking people with the
  level "nothing" (they are asked regardless).

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
  `TIME_ZONE`), `people` (many-to-many: who is asked), `paused_at`.
- **`Occurrence(question, asked_at)`**: one per time the question is
  asked.
- **Kind `answer`** (parent: its question), commentable:
  `Answer(Detail)` with `content` (Markdown) and `occurrence`; one per
  person and occurrence (unique on occurrence and creator), editable by
  its author. Its title is the question's, renamed with it (fixed
  2026-11-21: answers kept the old title in the feed and search).
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
- **Answers' mails** per `QuestionMail`: `each` through `notify()`;
  `summary` at 07:00 the morning after the occurrence (in `send_mails`),
  one mail with all answers.
- Staff create and edit questions; clients can be asked when the
  question is visible to clients.
- Clients only learn about the project's members among the people asked
  (staff of all-access projects needn't be members): the question page's
  people and "hasn't answered yet", the API's `people` and `missing`,
  and a person's answers (`/questions/<pk>/people/<user pk>/` and the
  API's `occurrences/?person_id=` are 404 for a client asking about a
  non-member; the API since 2026-11-21) (decided 2026-11-20 after the
  visibility review, `Project.people_known_to()`).

## Pages

- `/projects/<pk>/checkins/`: the project's questions with their
  schedule (`schedules.describe()`), next date and whether paused.
- `/questions/<pk>/`: the latest occurrence's answers (newest first) and
  who hasn't answered yet; older occurrences below, paginated by date;
  each answer with its comments. `?occurrence=` starts the list at that
  occurrence, `?before=` (a date) at the next older page.
- `/questions/<pk>/people/<user pk>/`: a person's answers over time.
- New and edit forms for questions (staff); pause and resume, and resume all of a project's paused check-ins together (the importer leaves them paused; `POST /api/v1/projects/{id}/checkins/resume/`, `biwak checkin resume --project ID`).
- The person's open questions ("due") on the project page.

## API and CLI

Endpoints for questions (list, create, update, pause), occurrences with
answers (cursor-paginated), answering, the mail mode.
`biwak checkins PROJECT`, `biwak checkin show QUESTION`,
`biwak checkin answer QUESTION [TEXT]` (standard input like comments),
`biwak checkin due` (what I haven't answered yet).

## Done when

Pages, API and CLI for all of the above. Tests: schedules across
daylight saving time changes and time zones (a question at 09:00
Europe/Zurich stays at 09:00 local time in March and October), pausing
and resuming, answering an older occurrence, one answer per person and
occurrence, the summary mail, a client asked on a visible question and not seeing
internal questions.
