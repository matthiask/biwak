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
- **Risks and questions:**

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
