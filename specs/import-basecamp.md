# Importing a Basecamp 4 account

For moving an existing team over: reads the Basecamp API and creates
projects, people and items.

**Status:** built (2026-11-21): `biwak/importer/` (`client.py` the API,
`convert.py` HTML to Markdown, `importer.py`, `images.py`,
`models.py` `ImportedObject`, `support.py` recorded shapes with made-up
data and a fake client for the tests). Not built: `--lazy-files`
(fetching old attachments when first opened), other people's bookmarks
(the API only gives the token owner's).

## Running it

`BASECAMP_TOKEN=... ./manage.py import_basecamp --account ID --project ID
[--project ID ...] [--dry-run] [--since YYYY-MM-DD] [--user EMAIL]
[--archive]`.
Always dry-run first: counts per kind, people to create, problems, what
goes into internal containers, archived recordings skipped.

- The token must be an administrator's: only they get the people's
  addresses (others get them redacted; the importer reports it and
  creates placeholder people `basecamp-ID@import.invalid`).
- The import runs as the token's owner (`/my/profile.json`, or
  `--user`), who must be Biwak staff: they create the projects and own
  the bookmarks.
- **Idempotent:** `ImportedObject(basecamp_id, basecamp_type,
  content_type, object_id)` maps what was imported, so a second run
  updates titles, texts, due dates, assignees, completion, archived
  lists, categories and visibility, and adds new comments; it doesn't
  change imported comments, positions or files. `--since` skips leaves
  (to-dos, cards, messages, docs, files, answers, comments) last updated
  before the date; containers are always read.
- **`--archive`** (decided 2026-11-22): archives each project in
  Basecamp (`PUT /projects/ID/status/archived.json`) once its import went
  through; a failed import archives nothing, projects already archived
  are left alone, a dry run lists what it would archive. Accounts may
  limit archiving to administrators and the project's creator: Basecamp
  answers 403 and the import stops there (rerun without `--archive`, the
  import itself is done).
- **Rates:** at most 50 requests per 10 seconds, 429 waited out
  (`Retry-After`); one request per recording for its comments and its
  subscribers, so big accounts take a while.

## Importing the whole account (planned, 2026-11-22)

Goal: import everything still current in one go (all active projects,
archived ones changed in the last few years) instead of project by
project. Waiting for Basecamp's account export to confirm the plan.

- **The API only lists projects you're on:** `/projects.json` gave 115
  active and at least 15 archived projects (only the first page of
  archived ones counted) for an account owner and admin, which isn't all
  of them.
- **The export as the source: probably not.** As far as we know it is a
  browsable HTML archive with the files, not the API's JSON. Check it
  for what the importer relies on: client visibility per recording (the
  rule that a client never sees what was internal depends on it),
  people's email addresses, Basecamp's IDs (a second run updates),
  subscriptions, check-in schedules, assignees as people. Parsing HTML
  would be a second, worse importer.
- **Plan:** the export as the inventory, the API as the source. Compare
  the export's project IDs with what the API lists; the person importing
  gets added to the missing projects in Basecamp; then a bulk selection
  in `import_basecamp` (e.g. `--all-active --archived-since DATE`)
  walking `/projects.json` and `?status=archived`. The API has no
  archiving date, so the cutoff would be the project's `updated_at`.
- **Runtime:** about two requests per recording (comments,
  subscribers) at 50 per 10 seconds: hours for a big account. Reruns
  update, so an interrupted run is simply started again.
- **Open questions:** the person importing becomes a member of every
  project they were only added to for the import (the importer copies
  Basecamp's members): skip them in those projects, or remove them
  afterwards? The cutoff for archived projects (3 years by
  `updated_at`?).

## Mapping

| Basecamp | Biwak |
| --- | --- |
| Project | Project, members with staff/client from Basecamp |
| To-do set, to-do list | List |
| To-do list group | Group of the list |
| To-do | To-do (assignees, due and start dates, completion, notes) |
| Card table | List with its columns as groups, shown as board |
| Card | To-do in its column's group; steps as a checklist in the notes (confirmed 2026-11-21: the reason for checklists in Markdown) |
| Message board, message | Message board, message (category by name, ignoring case, in the installation's one list; created when missing, with Basecamp's icon as its emoji; confirmed 2026-11-21) |
| Vault (folder), document, upload | Folder, doc, file |
| Questionnaire, question, answer | Check-in question, answer |
| Comment | Comment |
| Client visibility | Visible to clients on the container or item |
| Subscriptions, bookmarks | Subscriptions (who can see it), bookmarks |
| Schedule, chat, pings, forwards, wormholes | Not imported |

## Rules

- **Through the operations** (`AGENTS.md`), inside
  `activity.operations.importing(at=...)`: events notify nobody and carry
  the original time; the original times are set on items, comments and
  projects afterwards. Open pages and live editors still check access at
  once when an import changes who sees what.
- **Visibility** as in Basecamp, so a client never sees what was internal
  there: top-level containers and items get Basecamp's
  `visible_to_clients`, children inherit. What was **internal inside a
  visible container** goes into an internal "<container> (internal)"
  (decided 2026-11-21): a top-level folder for docs and files (nested
  folders flattened into it), a list for to-dos (groups of the same
  title; a board for a card table). An internal answer to a visible
  question can't move and is skipped and reported. A client's internal
  message stays internal.
- **People** by address. Those without an account are created
  **inactive** (never admins), as staff or client as in Basecamp, so
  nobody gets mail or a login before someone decides (`activation.md`);
  the operations accept inactive people only inside `importing()`.
  Companies become organizations by name, ignoring case and spaces:
  employees get the own organization, clients and collaborators their
  company's (collaborators become externals). Existing people keep theirs.
- **Profile images** (decided 2026-11-21): for people without an image
  in Biwak, `avatar_url` from `people/<id>.json` (`people.json` has
  null), processed like an upload, never overwriting one. Basecamp's
  generated ones (a flat square with initials, its beige placeholder)
  are skipped, told apart by content (`looks_generated()`: scaled to 64
  pixels, the four corners within 12 per channel, and quantized to 8
  colors the most common covering at least 60 %). A dry run fetches
  nothing; people with an image are never fetched again.
- **Rich text:** HTML to Markdown with `markdownify`
  (`biwak/htmlmarkdown.py`, shared with pasting); mentions of the
  project's people become `[@Name](person:ID)`, others stay `@Name`;
  files in texts are downloaded once and attached; links to imported
  recordings are rewritten.
- **Check-ins:** the schedule becomes a rule through
  `schedules.validate()` (`every_day` with days weekly on those,
  `every_other_week` interval 2, `every_month` by day or by
  `week_instance`: "the 2nd Monday", and "the last Monday" as the last
  one whether Basecamp says -1 or 5), in the installation's time zone
  (Basecamp's has none; confirmed 2026-11-21), `start_date` the first date. Imported **paused**, so Biwak
  doesn't start mailing people unasked. Occurrences come from the
  answers' `group_on`.
- **Archived** (decided 2026-11-21, `archiving.md`): archived to-dos
  come in completed at the recording's `updated_at`, by the importing
  person unless Basecamp names who completed it, with their comments;
  archived lists and projects stay archived; archived messages, docs,
  files and questions are skipped and listed in the report.
- **Not imported:** trashed recordings (anything in Basecamp's trash:
  to-dos, messages, docs, files, comments; confirmed 2026-11-21), pins of
  messages (not in the API), older versions of files, docs' history.
  Basecamp's API has no repeating to-dos.
