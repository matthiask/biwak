# Importing a Basecamp 4 account

For moving an existing team over. Reads the Basecamp API (OAuth, the
same endpoints the official `basecamp` CLI uses) and creates projects,
people and items.

**Status:** built (2026-11-21), branch `importer`: `biwak/importer/`
(`client.py` the API, `convert.py` HTML to Markdown, `importer.py` the
import, `models.py` `ImportedObject`, `management/commands/import_basecamp.py`,
`support.py` recorded shapes with made-up data and a fake client for the
tests). Not built: `--lazy-files`, Basecamp's bookmarks of people other than
the one whose token it is (the API only gives one's own). The decisions
and the questions the spec left open are under "Details of the build".

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`, with recorded API responses to work against. Recording
them (made up, see below) is the first step.

**Depends on:** every kind of item (`files.md`, `checkins.md`), mentions
and attachments.

## Mapping

| Basecamp | Biwak |
| --- | --- |
| Project | Project, members with staff/client from Basecamp |
| To-do set, to-do list | List |
| To-do list group | Group of the list |
| To-do | To-do (assignees, due dates, completion, notes) |
| Card table | List with its columns as groups, shown as board |
| Card | To-do in the group of its column |
| Message board, message | Message board, message (category by name) |
| Vault (folder), document, upload | Folder, doc, file |
| Questionnaire, question, answer | Check-in question, answer |
| Comment | Comment |
| Client visibility | Visible to clients on the container or item |
| Subscriptions, bookmarks | Subscriptions, bookmarks |
| Schedule, chat, pings, forwards | Not imported |

Basecamp stores rich text as HTML: convert it to Markdown
(`markdownify`), mentions (`<bc-attachment content-type=
"application/vnd.basecamp.mention">`) to `[@Name](person:ID)`, embedded
files to attachments (`files.md`).

## Model

`ImportedObject(basecamp_id, basecamp_type, content_type, object_id,
imported_at)`, unique on Basecamp ID and type: the mapping that makes a
second run update instead of duplicating.

## Requirements

- `./manage.py import_basecamp --account ID --project ID [--dry-run]
  [--since DATE]`, with the OAuth token from the environment
  (`BASECAMP_TOKEN`). Imports run per project.
- **Idempotent and resumable:** a second run updates; an interrupted run
  continues where it stopped.
- **Through the operations** (`AGENTS.md`), with the original authors and
  timestamps set afterwards; events get the original times and notify
  nobody (a flag on the operations' `record()` call, or importing with
  notifications switched off).
- **People** by email address; people without an account are created
  inactive, as staff or client as in Basecamp.
- **Attachments** in texts are downloaded and uploaded; links between
  items are rewritten to Biwak URLs. Optionally (`--lazy-files`),
  attachments of items older than a year are fetched when first opened.
- **Dry run** first: counts per kind, people to create, problems.
- **Rate limits:** Basecamp answers 429 with `Retry-After`; wait as told,
  at most 50 requests per 10 seconds otherwise.

## Done when

Tests against recorded API responses with made-up data (record the
shapes from the documentation at github.com/basecamp/bc3-api or from a
test account, then replace every name, text and address): every row of
the mapping, HTML to Markdown with mentions and attachments, a second
run updating, visibility as in Basecamp (a client must not see what was
internal there), the dry run.

## Details of the build

Run it: `BASECAMP_TOKEN=... ./manage.py import_basecamp --account ID
--project ID [--project ID ...] [--dry-run] [--since YYYY-MM-DD] [--user
EMAIL]`. The token must be an administrator's: Basecamp only gives them
the people's email addresses (others get them redacted, which the
importer reports and works around with placeholder people). The import
runs as the person the token belongs to (`/my/profile.json`, or `--user`),
who must be Biwak staff: they create the projects (and so become
members) and own the bookmarks.

Built the way the spec says: everything through the operations, inside
`activity.operations.importing(at=...)` (events notify nobody, carry the
original time), then the original times on the items, comments and
projects. Besides: `checkins.operations.add_occurrence()` and the public
`create_answer()`.

Proposed by the building agent (2026-11-21); marked **?** are the
questions the spec left open, built the safe way until answered:

- **Visibility** (decided by `access.md`, here only how it maps): the
  top-level list (to-do lists, card tables), message, folder, doc, file and
  check-in question gets Basecamp's `visible_to_clients`; what is inside a
  container inherits, as in both. What was **internal inside a visible
  container** can't be shown that way in Biwak (children have no switch):
  it is **skipped** and reported as a problem (**?**: a different home for
  it, e.g. an internal folder, or importing the container as internal).
  Messages by clients are visible in Biwak by definition: the importer
  sets the switch to what Basecamp had (a client's internal message stays
  internal).
- **People without an account** are created inactive, as staff or client
  as in Basecamp (never as admins), clients with their company as
  organization. The operations refuse inactive people (`add_member()`,
  `assign()`), so their memberships and assignments are written directly
  (**?**): once somebody activates them they are members. Without an
  address (not an administrator's token): a placeholder
  `basecamp-ID@import.invalid`, inactive, named as in Basecamp.
- **Check-ins:** the schedule becomes a rule through
  `schedules.validate()` (`every_day` with days is weekly on those days,
  `every_other_week` interval 2, `every_month` by the first date's day of
  the month or by `week_instance` for the nth weekday; **?** what
  `week_instance` means for "last"), the time zone is the installation's
  (**?** Basecamp's schedule has none), `start_date` the first date. They
  are imported **paused** (**?**), so that Biwak doesn't start asking and
  mailing people unasked; the answers' authors who can see the question
  are the people asked (Basecamp's respondents aren't in the API
  responses). Occurrences come from the answers' `group_on`.
- **Subscriptions** are set to Basecamp's subscribers of each recording
  who can see it (the creator's automatic one goes if Basecamp has none).
- **Rich text:** the converter is `markdownify`; divs become paragraphs;
  mentions of people on the project become `[@Name](person:ID)` (others
  stay `@Name`); files in texts are downloaded once (keyed by Basecamp's
  attachment ID) and attached; links to recordings already imported are
  rewritten when converting, the others when the project is done (comments
  have no operation to change them: those rows are updated directly).
  Card steps become a checklist at the end of the card's notes (**?**).
- **What isn't imported:** to-dos' start dates (no operation sets them),
  trashed recordings (**?**), archived recordings other than to-dos and
  lists (**?**: only to-dos and lists have a documented `status` filter),
  pins of messages (not in the API's documentation), older versions of
  files, docs without a history, schedule entries, chat, pings, forwards,
  wormholes. **Basecamp has no repeating to-dos in its API**, so there are
  no rules to convert for them.
- **Message categories** are looked up by name, and **created** when
  missing (**?**, categories are the installation's list).
- **Second run:** updates titles, texts, due dates, assignees,
  completion, archiving, categories and the visibility switch from
  Basecamp; adds new comments; doesn't change comments, positions or
  files already imported. `--since` skips leaves (to-dos, cards,
  messages, docs, files, answers, comments) last updated before the date;
  containers are always read.
- **Rates:** one request per recording for its comments and for its
  subscribers: big accounts take a while (50 requests per 10 seconds at
  most, and 429 is waited out).

## Decided after building (2026-11-21)

- Internal items inside a container visible to clients go into a
  separate internal folder (for files and docs: a top-level folder
  "<container> (internal)"; for to-dos: an internal list "<list>
  (internal)"), so nothing is lost and nothing leaks; the dry run lists
  them.
- People without a Biwak account are created inactive, and the
  operations accept inactive people only inside `importing()`
  (assigning, subscribing, memberships), so everything still goes
  through the operations; outside an import they keep refusing them.
- Imported check-ins stay paused; a project's paused check-ins can be
  resumed together (a button on the project's check-ins page, `POST
  /api/v1/projects/{id}/checkins/resume/`, `biwak checkin resume
  --project ID`).
