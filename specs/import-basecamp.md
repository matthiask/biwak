# Importing a Basecamp 4 account

For moving an existing team over. Reads the Basecamp API (OAuth, the
same endpoints the official `basecamp` CLI uses) and creates projects,
people and items.

## Mapping

| Basecamp | Biwak |
| --- | --- |
| Project | Project, members with staff/client from Basecamp |
| To-do set, to-do list | List |
| To-do list group | Group |
| To-do | To-do (assignees, due dates, completion, notes) |
| Card table | List with its columns as groups, shown as board |
| Card | To-do in the group of its column |
| Message board, message | Message board, message |
| Vault (folder), document, upload | Folder, doc, file |
| Questionnaire, question, answer | Check-in question, answer |
| Comment | Comment |
| Client visibility | Visible to clients on the container or item |
| Subscriptions, bookmarks | Subscriptions, bookmarks |
| Schedule, chat, pings, forwards | Not imported |

## Requirements

- Idempotent and resumable: Basecamp IDs are stored, a second run updates
  instead of duplicating. Imports run per project.
- Authors and timestamps are kept; events are created with the original
  times but send no notifications.
- Attachments in rich text are downloaded and re-uploaded; links between
  items are rewritten. Optionally, attachments of older items are fetched
  only when first opened, to start small.
- Mentions are mapped to people; people without an account are created
  inactive.
- A dry run reports counts and problems first.
- Rate limits are respected (Basecamp answers 429 with Retry-After).

## Tests

Against recorded API responses (made-up data), not a live account.
