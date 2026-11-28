# Check-ins

A question asked automatically on a schedule to chosen people, answers
collected in one place with comments: "What are you working on this
week?", "Read any good books lately?". Used heavily for the team itself,
less for client projects.

**Status:** built (2026-11-20). The code: `biwak/checkins/`
(`schedule.py` the time arithmetic, `operations.py` asking, summaries
and answering, `mails.py`).

## Decided

- **One time zone** (decided 2026-11-22): the installation's
  (`TIME_ZONE`), as for quiet hours (`quiet-hours.md`). Questions have
  no time zone of their own: no field, form field, API field or CLI
  `--zone`. Asking, occurrences and summaries are in the installation's
  time zone; `schedule.py` takes a zone, called with
  `schedule.time_zone()`.
- **No reminders** for missed check-ins (2026-11-20): the question mail
  is the only one asking; who hasn't answered shows on the question's
  page and in "due".
- **No skipping** (2026-11-20): without reminders it isn't worth having;
  "due" and "missing" mean not answered.
- **Answers' mails:** `QuestionMail(question, user, mode)`: `summary`
  (the default, decided 2026-11-20: ten mails per question are too
  many), `each` or `none`; choosing a mode other than `none` subscribes.
- **"No mails" stops them all** (decided 2026-11-21: check-ins aren't
  special compared to assigned to-dos): people whose mail delivery is
  "none" get neither question mails nor summaries (`mails._send_all()`);
  "due" on Home still asks them.
- **People asked and subscribers are two lists** (decided 2026-11-21):
  the people asked get the question mail and are "due"; the question's
  subscribers hear about the answers, whatever their level for the
  project ("subscribing is the switch", `notifications.md`). A question
  has the subscribers card like any item; created, its subscribers are
  the people asked plus its creator; changing who's asked later leaves
  them alone.
- **Anybody who can see the question answers** (decided 2026-11-21),
  asked or not: `can_answer()` is active and `can_see()`; pages, API,
  CLI and mail replies alike. Answering subscribes the author to their
  own answer, not to the question. One answer per person and occurrence;
  answering again changes it (also from the trash).
- **"People asked" is the people picker** (decided 2026-11-22, the
  user: choosing several at once; `PeopleField` with
  `offer_teams()`, `teams.md`), offering who sees the question once
  visible (the project's people, staff of an all-access project too;
  externals and clients as `access.md` says), by name. "Visible to
  clients" comes before it in "New check-in", and clients are offered
  only while it's ticked (`data-clients-follow`, `frontend/told.js`,
  like "Subscribers" when posting; unticking takes them away). Editing offers clients
  only while the question is visible; on an internal one the clients
  asked before stay as pills, others aren't offered. People asked who
  were deactivated or left stay too, in the form and through the API
  (`_check_people()`'s `kept`): kept, not added (decided 2026-11-28).
  Who isn't asked is marked (decided 2026-11-28): "People asked" on
  the question's page says "(inactive)", or "(not asked: can't see the
  check-in)" for who can't see it (left the project, a client on an
  internal question); the API's `people` carry `asked`
  (`ops.asked_ids()`: active and seeing the question, as `_recipients()`)
  and `biwak checkins show` marks them the same (CLI 0.79.0). Back, they
  are asked again.
- **Clients** are asked only on questions visible to clients; adding
  clients to an internal question is refused, and if it turns internal
  they stay in the list but aren't asked or mailed. They learn only about
  the project's members among the people asked (the page's people and
  "hasn't answered yet", the API's `people` and `missing`, a person's
  answers: 404 for a non-member, `Project.people_known_to()`; decided
  2026-11-20).
- People are asked whatever their level. No default time of
  day (the form asks). 5 occurrences per page.

## Model

- **Kind `question`** (no parent), switchable, not commentable:
  `Question(Detail)`, the question as the item's title, `rule` (an RRULE,
  `biwak/schedules/__init__.py`), `starts_on` (the first date the rule counts
  from, also the phase of "every two weeks"), `time_of_day`,
  `people` (who is asked), `paused_at`, `next_at` (stored, recomputed
  when one of them changes and after asking; empty while paused).
- **`Occurrence(question, date, asked_at, asked, summarized_at)`:** one
  per scheduled date in the installation's time zone (unique: editing the
  schedule on the day never asks a date twice); `asked` is whom it was
  asked, so who is missing is judged against them.
- **Kind `answer`** (parent: its question), commentable:
  `Answer(Detail)` with `content`, `occurrence` and `author` (unique per
  occurrence). Its title follows the question's.
- Audited: the tables people change (not `Occurrence`, not `next_at`).

## Asking

`./manage.py send_mails` (every minute) creates the occurrences due and
mails the question to its people, after the commit, one mail per person,
only to people still active and seeing the question then (checked again
after the commit). A mail which can't be sent is logged.

Traps the tests cover (`schedule.py`):

- **Wall-clock time:** 09:00 stays 09:00 in the installation's zone
  across daylight saving changes. A time which doesn't exist (02:30 when clocks
  go forward) is asked an hour later; one which happens twice, the first
  time. An occurrence's date is the rule's date, not the date of the
  moment it's asked (a gap just before midnight asks at 00:30 for the day
  before).
- **After downtime** a question is asked once, for the latest date due,
  not for every missed date.
- **Pausing** clears `next_at`; resuming counts from now, so missed
  occurrences aren't asked. Paused, trashed, archived questions and
  those of archived projects aren't asked. A project's paused questions
  resume together (the importer leaves them paused; `POST
  /api/v1/projects/{id}/checkins/resume/`, `biwak checkins resume
  --project ID`).
- **Editing the schedule** (the rule widget, `rule-widget.md`) counts
  from now: today's time only if still ahead, never a date already
  asked.
- **A stored rule which isn't valid any more** gives no date
  (`todos.md`): that question isn't asked and its `next_at` is cleared,
  the others and the summaries go on (`schedule.latest_due()` returns
  None; decided 2026-11-28 after one such rule stopped asking every
  question every minute).
- **A first date that doesn't match the rule:** the first date the rule
  gives on or after it; "every two weeks" counts its phase from the
  first date's week (fine as it is, 2026-11-20).
- **People** added are asked from the next occurrence; removing keeps
  their answers.
- **People away aren't asked** (decided 2026-11-22,
  `quiet-hours.md`): away on the day the question is asked (the
  installation's time zone), they get no question mail and aren't
  among the occurrence's people asked, so they aren't missing; the next
  occurrence asks them again. Their summaries wait while their mails
  wait (`HeldSummary`), checked again when they go (`quiet-hours.md`).

## Summaries and replies

- **The summary:** at 07:00 on the day after the occurrence's date in
  the installation's time zone, or the day after it was asked when that was
  later (after downtime), to subscribers in `summary` mode who see the
  question; none for an occurrence without answers; later answers
  aren't sent. An occurrence that was asked gets its summary also when
  the project is archived or the question paused meanwhile (decided
  2026-11-28: it was asked).
- **`each`** goes through the normal notifications to the question's
  subscribers; everybody else gets nothing per answer unless mentioned.
  "Each" counts only while the person is subscribed to the question (decided 2026-11-21): a choice left from before
  unsubscribing doesn't bring the answers back.
- **Replying** to the question mail answers that occurrence
  (`reply_headers()` in `biwak/checkins/mails.py`, `notifications.md`);
  the summary has no `Reply-To`.

## Pages, API and CLI

- `/projects/<pk>/checkins/`: the questions with their schedule
  (`describe()`), next date, paused; "Resume all".
- `/questions/<pk>/`: the latest occurrence's answers (newest first)
  and who hasn't answered; older occurrences below (`?occurrence=`,
  `?before=`); each answer with its comments.
- `/questions/<pk>/answer/` (`?occurrence=` for an older one);
  `/questions/<pk>/people/<user pk>/`: a person's answers.
- Staff create, edit, pause and resume questions; the person's open
  questions ("due") on the project page and Home.
- API: questions, occurrences with answers (cursor-paginated), answering,
  the mail mode, `GET /api/v1/me/checkins/due/`. CLI: `biwak checkins
  --project PROJECT`, `biwak checkins show|answer|due|create|pause|resume|mail`.
