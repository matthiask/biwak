# Verification rounds

Looking for behaviour the tests don't cover, above all scenarios combining
features over time, and keeping the open findings here until they're
fixed or decided (adapted from Workbench's `specs/verification.md`,
decided 2026-11-28 by the user).

**Status:** spec written (2026-11-28); rounds 1 and 2 run on
2026-11-28. Round 2's open findings and questions are below: the user
hasn't answered the questions yet.

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
  check-in questions and answers are updated; links to a list's group
  lead to the group on its list; archived to-dos without a completion
  are completed by nobody, at Basecamp's time; the same Basecamp file in
  texts of several items gets a row per item, sharing the stored file;
  "(internal)" lists and folders and their groups follow renames, and
  folders do too; a project's and a template's archived state comes from
  Basecamp only at the first import, both ways; people back with a new
  Basecamp ID haven't left (they were marked left and back in every
  run); a recording's comments are read again when its listing is newer
  than their cached answer.
- **To-dos:** stale to-dos are marked obsolete on the promised day;
  copies keep a group's "Keep untouched to-dos for a year" and
  deactivated assignees and people asked instead of failing; archived
  lists and lists in archived projects take no new or moved to-dos; the
  next to-do of a repeating one keeps deactivated assignees and
  subscribes the list's watchers; trashing the next to-do ends the
  series; the next to-do shares the files its notes show; `keep/`
  refuses completed and obsolete to-dos (page, API, CLI); the warning
  mail leaves out to-dos no longer stale since the run; `POST
  todos/{id}/move/` refuses completed to-dos and `previous_id` only
  names a to-do the reader sees.
- **People:** the API keeps deactivated assignees (one to-do and
  "Assign…" with `--replace`) and check-ins' people asked who were
  deactivated (the form too); the Django admin drops subscriptions when
  access is lost and activates through `activate()`; deactivating and
  "Reset sign-in…" remove push devices; single sign-on's 24-hour end
  keeps the push device; mentions of people deactivated later show
  their current name, linked, marked inactive; staff made client in the
  Django admin lose what they can't see and their teams, a client made
  staff only in the own or an external organization; inviting someone
  waiting to be activated activates them; activating with the mail
  someone in no project is refused; withdrawing an invitation unassigns
  before choosing between deleting and deactivating; "Reset sign-in…"
  counts push devices (CLI 0.78.0); an organization changed while
  somebody is inactive drops only the subscriptions they couldn't open
  once back.
- **Notifications:** a first mention merged into an edit marked unread
  is mailed and pushed; unsubscribing from a to-do stops its column
  moves, also through the mail's link; notifications of an item trashed
  or hidden when their mail is due are kept unmailed; one "Assign…"
  across projects is one entry in the digest; the outbox gives up
  retries to deactivated people and undeliverable addresses; the
  admins' notice names the outbox's retention (90 days); the
  "Subscriptions" bullet follows "Levels" (`notifications.md`);
  "Assign…" reads by acting like "Due date…" (`lantern.md`); a mention
  removed again within a merged edit doesn't count; mention syntax in
  forwarded mails isn't a mention (`forwarding.md`);
  `lantern.unread_counts()` counts in the database; switching from "No
  mails" to a mail per change sends what piled up as one digest-form
  mail (`lantern.md`); a list's watchers are subscribed to to-dos moved
  in or added from text, told of the latter by the list's one event
  (`notifications.md`), and of to-dos moved in by their moves, one
  entry and mail per "Move…" ("Ada moved 5 to-dos to Launch.",
  `notifications.md`); to-dos added from text tell the list's watchers
  only (`todos-from-text.md`); switching from the daily digest to a
  mail per change sends what waited as one digest-form mail
  (`lantern.md`).
- **Check-ins:** a held summary is checked again when it goes; a stored
  rule that isn't valid any more skips its question only; "People
  asked" marks who isn't asked, inactive or not seeing the question
  (page, API's `asked`, CLI 0.80.0); "away" is judged by the
  occurrence's date, not the run's.
- **Visibility:** a client's open list page is told when a to-do leaves
  it for an internal list; moving internal to-dos into a list clients
  see asks first, the API and CLI with `show_to_clients` (CLI 0.77.0);
  "visible to N clients" counts active and invited clients only; moving
  to another project ends public links; internal docs, files and
  folders into a visible folder, and visible to-dos into another
  project's visible list (new clients), ask first (CLI 0.79.0); "Move
  to…" of one to-do says when it hides; the API refuses
  `visible_to_clients` when creating in projects without clients; a
  client's `todos/?assignee=` with somebody they may not know finds
  nothing; the help says dragging stays within a list; clients who
  left don't count for the switch or "N clients", those waiting to be
  activated do; copying a list follows "no clients, no switch".
- **Docs and files:** a whole-text save from an old `base_version` is
  refused over the saver's own version with somebody else's typing
  merged into it (versions remember their co-authors); a form left open
  while its item moves to another project links what it uploaded;
  lists' descriptions link their files (the import's were deleted after
  a day); `fairy_tasks` saves typing left over before deleting unlinked
  files; the files in typing kept from somebody who lost access are
  linked; typing checks access again too, so a lost message doesn't let
  an open editor type into a doc made read-only.
- **API and CLI:** `biwak feed` and `biwak lantern` name events without
  an actor "Biwak" (CLI 0.76.0); the API's cursors are positions in the
  whole ordering.
- **Who did what:** the mails' signed links ("Keep open",
  unsubscribing) are logged as their recipient; names lose their
  accents instead of turning into escapes; a live save is logged as who
  typed it, not who caused it; nameless changes show 🧚, commands and
  migrations name themselves, sign-in addresses and linked accounts
  are audited, the webhook names "Inbound mail" and "Mail delivery"; PgBouncer keeps names per
  client (checked).

**To fix:** nothing left: the findings and the risks and questions
decided on 2026-11-28 are fixed (the "Fixed" list above).

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

**Data:** none. Checked 2026-11-28 (read-only, through `fl
manage-remote`): production has no check-in questions yet, so none with
a stored rule that isn't valid any more.

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

### Round 2 (2026-11-28)

All nine areas again, an agent each, four at once, in the same worktrees
and databases as round 1; the briefs named no hypotheses and pointed at
round 1's fixes as new code. Every bug below was shown by a throwaway
test which was run again before it was fixed (two exceptions, read from
the code: the mail reply below the quote, the tick's version). Fixed
(each in its part's spec, CLI 0.81.0):

- **Import:** comments `--since` skips that are in Biwak already don't
  keep their recording unread (the next run reopened a to-do completed
  in Biwak); a run stopped among a check-in's answers asks their authors
  the next time; no schedule again for a to-do completed and reopened in
  Biwak; Basecamp's people become members once, noted per person on the
  project's mapping (`ImportedObject.done`), and the importing person's
  bookmarks too: what was removed in Biwak stays removed, an interrupted
  run goes on, people new in Basecamp are added by nobody (the user,
  2026-11-28: "only at the first import" would have lost members to an
  interrupted first import).
- **To-dos:** the last to-do of a counted series keeps its 0 in the form
  and the API (saving the form made the series endless); the stale
  banner and "Keep open" go once the to-do is touched or `STALE_TODOS`
  is off; the dragging endpoints and the API's `lists/{id}/todos/move/`
  refuse completed to-dos.
- **Visibility:** the moves' questions count clients waiting to be
  activated (`shown_by_moving_into()`, `new_clients()`: every client in
  production waited, so they asked about "0 clients" or not at all), the
  project form's hint too; the API's feed gives "Tell them now"'s note
  to its writer and those told only, and no title of a list in a project
  the reader can't open; `lists-across-projects.md` said public links
  keep working after a move.
- **Notifications:** switching from the digest to a mail per change and
  back doesn't send a digest at once; a bookmarked item of a batch
  counts in the lantern as the menu shows it.
- **People:** no admin clients (the Django admin took both); a team
  doesn't keep a withdrawn invitation's account; the API doesn't invite
  into archived projects.
- **Docs and files:** a doc's live state isn't rewritten behind the open
  editors (a space or a line just typed was lost with the next words
  whenever somebody else opened the doc); "Save as a version" is kept
  (`DocVersion.kept`); no public links in archived projects; a
  template's new doc asks nobody whom to tell.
- **Check-ins:** a question whose stored rule isn't valid any more can
  be edited (a 500).
- **API and CLI:** a refused request changes nothing (every error
  answered rolls back; a 409 had lifted a doc's read-only option); NUL
  characters and `"archived": null` are 400s; `invitations/` names only
  projects the reader can open; the CLI repeats an upload after logging
  in again from the file's start (it stored an empty file).
- **Who did what:** edits merge into the 10 minutes before, never into
  a later edit (an import's edit at Basecamp's time took a person's edit
  of today back with it); every save merging somebody else's typing is
  logged as who typed; the history hides the groups of lists the viewer
  can't see ("another group").

**To fix** (verified, no decision needed, not done yet):

- **People:** the to-do's edit form, "Assign…" and a check-in's "People
  asked" name people already picked to clients and externals who may not
  know them (a removed member still assigned to a completed to-do):
  `assignable_or_assigned()`, `assignable_to_all_or_assigned()`,
  `checkins/views.py`'s "Those already asked stay"; they have to be kept
  without being shown, as the subscribers' modal does. The API's
  `todos/assign/` accepts such a person's ID too. The feed says
  "assigned it to ·" after a withdrawn invitation's account is deleted
  (`assigned` and `unassigned` events store IDs only).
- **Docs:** a whole-text save is refused with "… saved a newer version"
  when only the saver changed anything since (the co-authors carried
  over to the replaced version, round 1's fix); a tick on a doc's
  reading page answers with the version of the merged text, others'
  unsaved typing included, so the next tick can hit the wrong box.
- **CLI:** a check-in's "Next" is UTC beside its local time of day
  (`[:16]` of the API's timestamps, CLI-wide); `biwak messages --project
  P --limit N` reads one page only (and `--json` prints the page object:
  changing that is a decision).
- **Who did what:** a column's title of the project a to-do came from
  shows in its events to everybody in the new project, clients too
  (`data["group"]`, `_event.html`); "Save as a version" by somebody who
  typed nothing gives them an `edited` event when others' typing is
  merged.

**Questions** (asked 2026-11-28, open; the first proposal is what we
would do):

- **Import:**
  1. Items the import can't write on (a to-do or folder moved to another
     project in Biwak, a doc made read-only) stop this and every later
     run (`_move_todo()`, the creates with `parent=` in another project,
     `update_doc()` raising `DocReadOnly`): skip, list under "Problems",
     go on?
  2. Trashed and restored in Basecamp stays in Biwak's trash, is purged
     after 30 days and never imported again: restore, unless trashed in
     Biwak too?
  3. A change in Basecamp deletes subscriptions made in Biwak and
     subscribes again who unsubscribed: only add, respecting
     unsubscriptions?
  4. Undoing an edit made in Biwak (title, notes, dates, assignees, the
     list) is dated before the edit: "now", like completions (decided
     2026-11-27 for those)?
  5. New Basecamp to-dos in a list internal in Basecamp and shown in
     Biwak are visible at once: keep, or an "(internal)" twin?
  6. New Basecamp to-dos in a list in Biwak's trash arrive active:
     import them trashed? A to-do moved in Biwak to an internal list (to
     hide it) goes back with any change in Basecamp (by "Basecamp wins").
- **To-dos:** moving the due date of a to-do repeating every N weeks or
  months shifts the series for good (the anchor is the current due date;
  three of production's seven distinct rules are quarterly): a stored
  anchor? "All to-dos" of an archived project or a template says
  "Nothing to do." (`due.todos()`): show them, or drop the links? Ticked
  boxes are copied ticked into the next repeating to-do: untick?
- **Visibility:** a to-do visible in one project, moved internal into
  another, renamed and shown there shows the new clients its events from
  the first project: hide the past when an item arrives internal? A
  reply by mail to a notification from when the item was internal is
  posted visibly now: keep, or refuse? "New list" in the selection's
  "Move…" into a project without clients makes a visible list. Restoring
  from the trash into a list shown meanwhile asks nothing. Admins' "All
  public links" lists titles of limited projects (decided 2026-11-22,
  still wanted?).
- **Notifications:** a to-do moved into a watched list and back out
  still tells its watchers, and they stay subscribed (also to to-dos
  moving on: drop the automatic subscription when a to-do leaves the
  list?); a reply by mail written below or between the quote is dropped
  silently (`strip._cut()`): keep the unquoted lines after the header?
  Assigned and unassigned within 10 minutes still mails "assigned you";
  a push due just outside the working time is dropped, not sent at its
  start; a thread that never rests for 10 minutes is never mailed (no
  cap); a later delivery doesn't clear the undeliverable mark; a watcher
  who unsubscribed from a repeating to-do is subscribed to the next one.
- **People:** somebody waiting to be activated who'll never come can't
  be deactivated; "Withdraw" is offered for imported people activated
  with the mail; resending an invitation to somebody in no project sends
  a bare "invited you to Biwak"; own staff made externals stay assigned
  in templates (and are added to every project made from them); a former
  staff member made a client still changes the visible lists and docs
  they created.
- **Docs:** two people taking turns get a version per turn; to-dos in an
  archived list keep and get public links; `tell_unanswered()` tells
  about a doc whose project was archived within the hour.
- **Check-ins:** "Unsubscribe from this" in the question mail only ends
  the summaries and says otherwise: explain on the page, as for assigned
  to-dos? Summaries held while away go out one mail per occurrence; a
  question in the trash at 07:00 and restored afterwards never sends
  that summary; a client's link on an answer's author who isn't a member
  is a 404; people asked who come back aren't subscribed again; the form
  requires somebody asked, the API doesn't.
- **API and CLI:** refuse empty uploads like the page? A default text
  for 403s without one; the CLI repeating the API's words ("Send
  “show_to_clients”: true"); what the web does without an endpoint or a
  command (ticking, a doc's "Tell people", marking unread, renaming a
  person, the files' bulk move and trash; archiving projects and editing
  check-ins in the CLI); `todos show` says "somebody" for a completion
  by nobody.
- **Who did what:** the history shows "Basecamp import" creating
  imported items and "Completed" twice; API tokens' `key_hash` and push
  endpoints stay in the audit log's `row_data`; the next repeating
  to-do's `created` event names who completed the last one, its creator
  is the first one's.

**Risks** (not shown by a test): a switch and a create or move at the
same moment can leave the stored visibility wrong until
`check_visibility` (no lock on the root); `move_item()` saves the whole
row; the outbox retries to an account deleted since, and after a 429
skips the check for deactivated people; what somebody who lost access
typed can come back with another editor's reconnect; an open editor
stays in its old project's channel group after the doc moves; a
transient storage error is stored as "no preview" for good; unlinked
attachments are deleted after a day while their form or offline editor
is still open; the answer cache's pages expire separately; a person back
with a new Basecamp ID is "left" between two processes; sign-in flows
are logged as anonymous; `user_name_kept()` can mask a database error;
column moves merge across a move to another list; `starts_on` of a
check-in has no lower bound (a mistyped year makes each asking slow);
an external's `PATCH` of "People asked" drops those they weren't shown;
moving something out of a visible folder to the top level hides it;
`STALE_TODOS` turned on again marks what was warned before obsolete at
once; the calendar feed's `DTSTAMP` doesn't move with the dates.
