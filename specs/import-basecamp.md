# Importing a Basecamp 4 account

For moving an existing team over. Reads the Basecamp API (OAuth, the
same endpoints the official `basecamp` CLI uses) and creates projects,
people and items.

**Status:** open.

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
