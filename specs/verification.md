# Verification rounds

Looking for behaviour the tests don't cover, above all scenarios combining
features over time, and keeping the open findings here until they're
fixed or decided (adapted from Workbench's `specs/verification.md`,
decided 2026-11-28 by the user).

**Status:** spec written (2026-11-28); round 1 run 2026-11-28, its
findings open below.

## Why

Each part is tested on its own; the bugs found in use are in the
combinations and in what happens later. Found on 2026-11-28 alone: an
import run stopped halfway left a person "Inactive" instead of "People
who left" (later runs skip unchanged recordings, so she was never looked
at again); later runs recorded Basecamp's changes in the creator's name,
so somebody who had left months before "edited" a to-do; links between
projects imported in a different order stayed Basecamp's; every live
update marked the forms that scripts had changed as new.

## When

From time to time: after a batch of parts is merged, before a larger
Basecamp import, or when the user asks what we're missing. A round is
started by the user or proposed to them, never on its own (agents cost
time and load the machine).

## A round

1. **Pick the areas** (below) and give each to an agent of its own, at
   most four at once (`AGENTS.md`: several agents running tests had the
   machine at a load above 13). The brief: read `AGENTS.md`, `SPEC.md`,
   the area's specs, the code and the tests, **read-only and without our
   hypotheses**; what's covered already (the tests, the area's commits
   in `git log`, the findings of earlier rounds below); look for
   scenarios over time and across parts, through every entry point.
   Separate **verified bugs**, each shown with a throwaway test (run
   alone: `./runtests.sh <module> --exclude-tag e2e --parallel 1`; a
   browser test only for JavaScript or htmx) which it deletes
   afterwards, from **untested risks** and **questions** (behaviour the
   specs don't decide). Each finding: the scenario step by step, what
   happens, what the spec says or what would be expected, the code
   (`file:line`).
2. **Check every finding** against the code before relying on it: run
   the throwaway test again, read the lines. Agents' findings come back
   as sure as their mistakes.
3. **Ask the user** where the behaviour is a decision rather than a bug,
   several questions at once; the answer goes into the part's spec
   (dated) and here.
4. **Fix the bugs** as `AGENTS.md` says ("Fixing bugs": the failing test
   first): a branch per area, one commit per fix with its test, help and
   spec; merged, pushed in a batch. Tests go next to the code, browser
   tests only for JavaScript and htmx, CLI round trips into
   `biwak/test_cli.py`.
5. **Keep the open findings here** until they're done, so that the next
   session continues there; fixed ones are summed up in a line (git keeps
   the rest), decisions stay listed under their round.

**Data:** the user may pull a copy of production into the local
database; agents may read it to check a finding (counts, shapes), never
change it, and nothing of it goes into this file, tests or commits
(`AGENTS.md`, "Data": made-up names only; "a person who left", "a to-do
in a project imported later").

## Areas

What each agent looks at; scenarios over time, across parts and through
every entry point. Not CSS layout (screenshots, `AGENTS.md`).

- **Visibility** (`access.md`): switches on containers, moving items
  between visible and internal places, what clients create and change,
  members joining and leaving, the stored visibility against the tree
  (`check_visibility`). Through every entry point: pages, the feed and
  item histories, the lantern, search, Home, mails and digests, replies
  by mail, web pushes, live updates and the docs' websockets, the API and
  the CLI, public links, attachments' URLs, the calendar feed, the
  palette, the Basecamp trampoline.
- **The Basecamp import** (`import-basecamp.md`): later runs (skipping
  unchanged recordings, `--since`, `--full`), runs stopped halfway and
  started again, Basecamp winning over changes made in Biwak meanwhile,
  people leaving and coming back, who and when events name, links
  between projects imported in any order, the caches.
- **To-dos over time** (`todos.md`, `start-dates.md`, `stale-todos.md`):
  repeating to-dos completed, reopened and marked obsolete, start and due
  dates, moving between lists and projects, copying lists, templates,
  archiving lists, the trash and its 30 days, the to-dos page's filters
  and groupings.
- **People** (`people.md`, `organizations.md`, `activation.md`,
  `handover.md`, `teams.md`): activating, deactivating, leaving,
  handing over, changing organizations (externals), teams, inactive
  assignees and subscribers, mentions of people who can't see the item.
- **Notifications** (`notifications.md`, `lantern.md`, `quiet-hours.md`,
  `web-push.md`, `mail-sending.md`): subscriptions and levels, quiet
  hours, digests, replies by mail, pushes, the outbox's retries, bounces,
  the lantern's counts and reading by acting.
- **Docs and files** (`files.md`, `collaboration.md`, `editor.md`,
  `public-links.md`): editing live and through the API at once, versions,
  drafts, read-only docs, ticking checklists, attachments, moving between
  folders.
- **Check-ins** (`checkins.md`): schedules, pausing, summaries, people
  asked who leave or lose access.
- **API and CLI** (`api-cli.md`): the same operations, permissions and
  visibility as the pages, `MINIMUM`, the agent skills' commands.
- **Who did what** (`auditing.md`): the audit log's user names
  (requests, tokens, `fairy_tasks`, the importer), events' actors and
  times.

## Rounds

Each round gets a section: the date, the areas and agents, a line on
what was fixed (the commits after "Verification: …"), and the open
findings:

- **To fix:** verified bugs and decided changes, by area, until fixed.
- **Decided, no change:** behaviour the user decided stays.
- **Data:** what to fix in production's data, without names.
- **Risks and questions:** open until tested or decided.
- **Ideas:** for later, not findings.

### Round 1 (2026-11-28)

All nine areas, an agent each, four at once, each in its own worktree
and database (`../biwak-verify-<area>`, `biwak_verify_<area>`, no
`STORAGE_URL` or `RESEND_API_KEY`). Every bug below was shown by a
throwaway test that was run again and failed before it was listed.
Fixed (each in its part's spec):

- **Import:** later runs leave recordings unchanged in Basecamp alone
  (Biwak's changes stay); a dry run writes nothing for projects imported
  before; moves in Basecamp are followed; trashed in Basecamp is trashed
  here, deleted here isn't imported again; a project archived in
  Basecamp is archived only at its first import; renames and archiving
  of projects and templates name nobody, at Basecamp's time; new files
  in texts changed in Basecamp are linked; `--since` doesn't store a
  recording as completely read when it skipped older comments; changed
  check-in questions and answers are updated.
- **To-dos:** stale to-dos are marked obsolete on the promised day;
  copies keep a group's "Keep untouched to-dos for a year" and
  deactivated assignees and people asked instead of failing; archived
  lists and lists in archived projects take no new or moved to-dos; the
  next to-do of a repeating one keeps deactivated assignees and
  subscribes the list's watchers.
- **People:** the API keeps deactivated assignees (one to-do and
  "Assign…" with `--replace`) and check-ins' people asked who were
  deactivated (the form too); the Django admin drops subscriptions when
  access is lost and activates through `activate()`; deactivating and
  "Reset sign-in…" remove push devices; single sign-on's 24-hour end
  keeps the push device.
- **Notifications:** a first mention merged into an edit marked unread
  is mailed and pushed; unsubscribing from a to-do stops its column
  moves, also through the mail's link; notifications of an item trashed
  or hidden when their mail is due are kept unmailed; one "Assign…"
  across projects is one entry in the digest; the outbox gives up
  retries to deactivated people and undeliverable addresses; the
  admins' notice names the outbox's retention (90 days).
- **Check-ins:** a held summary is checked again when it goes; a stored
  rule that isn't valid any more skips its question only.
- **Visibility:** a client's open list page is told when a to-do leaves
  it for an internal list; moving internal to-dos into a list clients
  see asks first, the API and CLI with `show_to_clients` (CLI 0.77.0);
  "visible to N clients" counts active and invited clients only; moving
  to another project ends public links; internal docs, files and
  folders into a visible folder, and visible to-dos into another
  project's visible list (new clients), ask first (CLI 0.78.0); "Move
  to…" of one to-do says when it hides; the API refuses
  `visible_to_clients` when creating in projects without clients; a
  client's `todos/?assignee=` with somebody they may not know finds
  nothing.
- **Docs and files:** a whole-text save from an old `base_version` is
  refused over the saver's own version with somebody else's typing
  merged into it (versions remember their co-authors); a form left open
  while its item moves to another project links what it uploaded.
- **API and CLI:** `biwak feed` and `biwak lantern` name events without
  an actor "Biwak" (CLI 0.76.0); the API's cursors are positions in the
  whole ordering.
- **Who did what:** the mails' signed links ("Keep open",
  unsubscribing) are logged as their recipient; names lose their
  accents instead of turning into escapes; a live save is logged as who
  typed it, not who caused it.

**To fix:** the findings are fixed. From the risks and questions,
decided by the user on 2026-11-28 (or following a rule already
decided, marked "consistent"):

- **To-dos:**
  - Trashing the next to-do of a repeating one ends the series (decided):
    `todos.md`'s "not in the trash" clause goes.
  - The next to-do shares the attachments its notes show: rows of its
    own pointing at the same stored file, which is deleted with its last
    row (decided; moves don't rename stored files).
  - `keep/` refuses completed and obsolete to-dos (page, API, CLI) like
    the mail's link (consistent).
  - The warning mail leaves out to-dos no longer stale since the run
    (commented on, archived; consistent with `_still_warned()`).
  - `POST todos/{id}/move/` refuses completed to-dos like the page
    (consistent); the API's `previous_id` only names a to-do the reader
    sees (consistent).
- **Notifications:**
  - People watching a list ("Everything") are subscribed to to-dos moved
    in or added from text, and told about them like new to-dos (decided).
  - "Assign…" reads by acting like "Due date…" (consistent).
  - `notifications.md`'s "Subscriptions" bullet follows "Levels".
  - Switching from "No mails" (or after held mails) sends what piled up
    as one digest-form mail, mails per change from then on (decided).
  - `unread_counts()` counts in the database; mention syntax in
    forwarded mails isn't a mention; a mention removed again within a
    merged edit doesn't count (consistent).
- **People:**
  - Mentions of people deactivated later show their current name,
    linked, marked inactive (decided).
  - Staff made client in the Django admin lose what they can't see
    (assignments, subscriptions) and their teams; a client made staff
    only in the own or an external organization, else refused (decided).
  - Inviting someone waiting to be activated activates them (decided);
    activating with the mail someone in no project is refused (decided).
  - Withdrawing an invitation unassigns before choosing between
    deleting and deactivating; "Reset sign-in…" counts push devices
    (consistent).
- **Visibility:**
  - Help: dragging stays within a list (`docs/todos.md`).
- **Check-ins:** "People asked" marks who isn't asked (inactive, can't
  see it; decided); "away" is judged by the occurrence's date
  (consistent).
- **Docs and files:** `fairy_tasks` saves pending typing before deleting
  unlinked attachments; attachments inserted by someone who lost access
  are linked when their typing is kept; lists' descriptions link their
  attachments (`create_list`/`update_list` never call `link()`, to
  check); read-only takes effect for open editors at once (to check).
- **Who did what:** nameless changes show 🧙 in the history, as in
  Workbench; management commands and migrations name themselves;
  allauth's social accounts and sign-in addresses are audited (tokens
  and secrets left out); the inbound webhook names "Resend" (decided:
  as complete as reasonably possible). Production reaches PostgreSQL
  through PgBouncer in transaction mode: check that `SET SESSION
  application_name` stays with its client there, fix it if not.
- **Import:** links to a list's group lead to the list in Biwak;
  archived to-dos without a completion are completed by nobody, at
  Basecamp's time; the same Basecamp attachment in two texts gets an
  attachment per item; "(internal)" lists and folders follow renames and
  a renamed group isn't doubled; a project's (and template's) archived
  state comes from Basecamp only at the first import, both ways; people
  back with a new Basecamp ID (to check); comments read fresh when a
  listing is newer than the cached answer (consistent).

**Decided, no change:**

- Clients see who completed a visible to-do, also somebody they
  otherwise may not know: acting in a visible place counts (decided
  2026-11-28).
- Unarchiving or restoring a list doesn't restart its to-dos' 90 days
  (decided 2026-11-28).
- The next to-do of a repeating one copies the old one's subscribers and
  adds the list's watchers; moving out of an archived list is allowed;
  the "Assign…" picker offers inactive people assigned to some of the
  selected to-dos; something deleted in Biwak is never imported again
  (agents' choices, kept).
- Summaries of an asked occurrence go out also when the project was
  archived or the question paused meanwhile (`checkins.md`).
- A doc told an hour after its last change names its creator also when
  they left or were removed (`files.md`).

**Data:** check production for check-in questions with a stored rule
that isn't valid any more (the bug above stops asking for everybody).

**Risks and questions:**

- Search pages by `-updated_at`: something edited while being read
  moves to the top and is missed (nothing repeats).
- `check_visibility` compares items only, not events or notifications;
  the live editor re-checks access every 5 seconds at most.
- "Move by N days" shifts the "repeats until" of to-dos without a due
  date when copying a list, not with "Due date…".
- Import: imported check-in occurrences have nobody asked; a check-in
  question's visibility isn't followed (it would show answers internal
  in Basecamp); comments, groups, check-in questions and email forwards
  trashed in Basecamp aren't followed (Biwak can't trash them, or the
  listing refuses the type); what was moved into an "(internal)" list or
  folder isn't trashed with its original.
