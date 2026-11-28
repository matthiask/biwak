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
Fixed: the API keeps deactivated assignees (one to-do and "Assign…"
with `--replace`) and check-ins' people asked who were deactivated
(the form too); the Django admin drops subscriptions when access is lost
and activates through `activate()`; deactivating and "Reset sign-in…"
remove push devices.

**To fix** (decisions by the user, 2026-11-28; each goes into its
part's spec with the fix):

- **Import, later runs** (`import-basecamp.md`):
  - A recording unchanged in Basecamp isn't touched at all: today the
    listing's visibility, completion, assignees and archived state still
    undo what was changed in Biwak (a to-do completed, an assignment, a
    list hidden from clients, an archived project), and the visibility
    events are dated before the change they undo; check-in questions put
    the people taken off back on (`importer.py` `_todo`, `_todolist`,
    `_top_visibility`, `_status`, `_project`, `_question`). Decided:
    Biwak's change stays; toggles that don't change `updated_at` come
    with `--full` only.
  - A dry run writes for projects imported before (completion,
    assignees, archiving, events): the callers of `_upsert()` keep
    writing on the object it returns.
  - Moves in Basecamp are followed (decided): to-dos between lists,
    cards between columns, docs and files between folders, with the new
    place's visibility. Today nothing moves, so a to-do or doc moved
    into an internal place stays visible to clients.
  - A project archived in Basecamp is archived in Biwak only at its
    first import (decided); today a rerun after `--archive` archives the
    project people work in, ending its public links.
  - Trashed in Basecamp means trashed in Biwak; something deleted in
    Biwak isn't imported again (decided; today both are ignored or come
    back).
  - Renames of projects and templates, and their archiving, name nobody
    at Basecamp's time (today the importing person, now; `update_project`
    refuses `actor=None`).
  - A new attachment in a text changed in Basecamp is never linked
    (`attachments.link(actor=None)` links only the actor's uploads), so
    the cleanup deletes it a day later; to-dos, messages, files.
  - `--since` stores a recording as completely read although its older
    comments were skipped; they come only with `--full`.
  - Check-in questions and answers changed in Basecamp aren't updated
    (`_upsert` without `update=`).
- **To-dos:**
  - Stale to-dos are marked obsolete a day after the date the mail and
    the banner promise when the run starts a little earlier or across
    the spring DST change (`stale.mark_warned()` compares timestamps,
    `obsolete_on()` dates).
  - Copying a list or a template keeps a group's "Keep untouched to-dos
    for a year" (decided; today 90 days).
  - Archived lists and lists in archived projects refuse new and moved
    to-dos at every entry point, like `may_add_to()`: the inline form,
    the API's create and move, dragging; a repeating to-do in an
    archived project creates no next one (decided).
  - The next to-do of a repeating one keeps deactivated assignees
    (decided; today `_assignable()` drops them) and subscribes the
    list's watchers (today it copies the old to-do's subscribers).
- **People:**
  - Copying a list, a project from a template, or a template's check-in
    with a deactivated assignee or person asked fails (`subscribe()`
    raises; the copy page shows the untranslated error, the API 500).
- **Notifications:**
  - A first mention merged into an edit whose notification was marked
    unread is mailed and pushed (decided; today neither).
  - Unsubscribing from a to-do also stops hearing about its column moves
    as a list's watcher; the mail's unsubscribe link unsubscribes from
    the to-do only (decided).
  - Notifications of a trashed item (or one the person can't see for
    now) are kept unmailed, not deleted, so restoring brings them back
    unread (decided; `mails._prepare()` deletes them).
  - One "Assign…" across projects is one entry in the digest (today one
    per project).
  - The outbox gives up retries to deactivated people and undeliverable
    addresses (decided).
  - The admins' notice says the outbox keeps mails 30 days; it's 90.
  - A held summary still goes out after the person chose "No mails",
    unsubscribed, or every answer was trashed (`send_held_summaries()`).
- **Visibility:**
  - Moving internal to-dos into a list clients see asks first, like the
    switch; the API and CLI need an explicit flag (decided).
  - A client's open list page isn't told when a to-do leaves it for an
    internal list (`live.changed()` takes the target's visibility).
- **Check-ins:** one stored rule that isn't valid any more stops asking
  the rest and the summaries every minute (`latest_due()` on `None`).
- **Docs and files:**
  - A whole-text save with an old `base_version` overwrites someone
    else's typing merged into a version credited to the saver (the
    conflict check skips the saver's own versions).
  - An editor left open while its doc moves to another project uploads
    attachments to the old project, never linked, deleted a day later.
- **API and CLI:**
  - `biwak feed` and `biwak lantern` crash on events without an actor
    (stale to-dos, the import), every CLI down to `MINIMUM`; the skills
    don't say `actor` may be null.
  - Cursor pagination skips or repeats rows when something leaves or
    joins an earlier page where the first ordering field is shared
    (messages: `pin_key`; `todos/`: the project, the due date).
- **Who did what:**
  - A live save names the authors of the typing it merges (decided;
    today whoever triggered it, also a client who only opened the page).
  - "Keep open" from the stale mail is logged as anonymous or whoever is
    signed in, not the recipient; links signed for a person run as them.
  - Single sign-on's 24-hour sign-out deletes the push device (expiring
    sessions keep it, `web-push.md`), logged under the connection's
    previous name (it runs before `user_middleware`).
  - Names that aren't ASCII are garbled in `user_name`
    (`application_name`).

**Decided, no change:**

- Summaries of an asked occurrence go out also when the project was
  archived or the question paused meanwhile (`checkins.md`).
- A doc told an hour after its last change names its creator also when
  they left or were removed (`files.md`).

**Data:** check production for check-in questions with a stored rule
that isn't valid any more (the bug above stops asking for everybody).

**Risks and questions:**

- Import: the answer cache can mix ages (a recording's listing fresh,
  its comments from the dry run); the same Basecamp attachment ID in two
  texts reuses one attachment, possibly across projects; "(internal)"
  lists and folders keep old names, a renamed group gets a second one;
  people back with a new Basecamp ID; links to a list's group lead to
  Basecamp; archived to-dos without a completion are completed by the
  importing person.
- To-dos: a trashed next to-do takes its series with it (the rule moved
  to it), so the "not in the trash" clause in `todos.md` is dead; `keep/`
  accepts completed and obsolete to-dos (page, API, CLI); the warning
  mail can list to-dos commented on since the run; unarchiving or
  restoring a list puts its old to-dos up for warnings; "Move by N
  days" shifts "repeats until" of undated to-dos in copies only;
  `POST todos/{id}/move/` moves completed to-dos the page won't; the
  API's `previous_id` names trashed or other projects' to-dos; the next
  to-do copies notes but not their attachments.
- People: mentions of people deactivated later show the label as
  written, no link, no "(inactive)"; staff made client keep internal
  assignments and teams, a client made staff turns their organization
  external; inviting an imported person not activated yet says
  "deactivated"; activating with the mail someone in no project sends
  an empty invitation; withdrawing an invitation deactivates where
  deleting would work.
- Notifications: to-dos added from text or moved in don't subscribe
  watchers; "Assign…" doesn't read by acting, "Due date…" does;
  `notifications.md` contradicts itself on new to-dos in a followed list
  at "only what concerns me" (the code follows "Levels"); switching from
  "No mails" mails everything unread at once; `unread_counts()` loads
  every unread notification; a forwarded mail with mention syntax
  mentions members; a mention removed within a merged edit still counts.
- Visibility: `completed_by` isn't filtered for clients; "visible to N
  clients" counts inactive clients; `check_visibility` checks items
  only; the live editor's 5-second re-check window.
- Check-ins: imported
  occurrences have nobody asked; "away" is judged by the run's day;
  "People asked" lists people who left; people coming back are asked
  again silently; later imports and Basecamp's schedule or pausing.
- Docs and files: `fairy_tasks` deletes unlinked attachments before
  saving pending typing; attachments by someone who lost access stay
  unlinked; read-only isn't immediate for open editors; public links
  survive a move into a limited project.
- API and CLI: search pages by `-updated_at`; a client may filter
  `todos/?assignee=` by people they may not know; the API accepts
  `visible_to_clients` in projects without clients.
- Who did what: the name is per connection (a reconnect in a long run,
  a pooler, a higher `CONN_MAX_AGE`); the inbound webhook never sets
  "Resend"; migrations and commands by hand write no name; linked
  social accounts and sign-in addresses aren't audited.
