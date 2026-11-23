---
name: biwak-weekly-summary
description: Summarize a project's last 7 days in Biwak (the project management tool for teams working with clients) with the `biwak` CLI, what was done and started, messages and docs, decisions, what's open and overdue, each with its link; posted as an internal message only on request. Use when the user asks for a weekly summary, a status report, a recap or what happened in a Biwak project this week.
---

# A project's week in Biwak

The `biwak` CLI talks to Biwak (see `biwak --help`). If `biwak` isn't
installed or logged in, tell the user to run
`uv tool install "git+https://github.com/matthiask/biwak#subdirectory=cli"`
and `biwak login URL --write` (`--read` is enough unless the summary is
posted), which authorizes `biwak` in the browser. If a command or option
below is missing, `uv tool upgrade biwak-cli`.

The summary is shown to the user; it's posted only when the user asks,
as an internal message.

## 1. Read the week

Find the project (ask when the name matches several), and today's date:

    biwak me --json
    biwak projects --json

What happened over the last 7 days (`--since` is the date 7 days ago),
newest first:

    biwak feed --project <project> --since <date> --limit 1000 --json

Each event has its `action` (`created`, `completed`, `commented`, …),
the `actor`, the `item` (`id`, `kind`, `title`, `url`,
`visible_to_clients`), `data` and an `excerpt` of comments and
messages. If it returns 1000 events, say the week is cut off there.

What's open, by due date:

    biwak todos --project <project> --due overdue --json
    biwak todos --project <project> --by-due --json

Read the messages, to-dos and docs that had comments or are new this
week, for what was decided:

    biwak messages show <message> --comments --json
    biwak todos show <todo> --comments --json
    biwak docs show <doc> --comments --json
    biwak checkins --project <project> --json
    biwak checkins show <question> --json

## 2. Summarize

Short, in the user's language, each line with its link (the item's
`url`):

- **Done:** to-dos completed this week (`completed` events of to-dos
  still completed), by list.
- **New:** to-dos created and still open, new messages and docs, files
  uploaded.
- **Decisions:** what messages and comments decided or agreed on, in a
  sentence each, with who said so; quote when the wording matters. Only
  what the texts say: no guesses about decisions nobody wrote down.
- **Open and overdue:** overdue to-dos with their assignees and due
  dates, then what's due in the coming week.
- **Questions:** open questions in comments nobody answered yet.

Leave out the noise: reactions, moves, edits, completing and reopening
the same to-do. Mark what clients can see with "[clients]".

## 3. Post, only when asked

When the user asks for it, write the summary as Markdown to the
scratchpad and post it as an internal message (without `--visible`):

    biwak messages create <project> <title> --json < <scratchpad>/summary.md

A title like "Week 48: Website relaunch" in the user's language. It
tells those who want to hear about new messages; `--also <ids>` only
for people the user names.

**Visible to clients** only when the user asks for that separately and
confirms it: clients would see the message. Before, rewrite the summary
from what clients can see only (`visible_to_clients` on every item and
event): leave out internal to-dos, messages, docs and comments entirely,
show the rewritten text to the user, then post it with `--visible`:

    biwak messages create <project> <title> --visible --json < <scratchpad>/summary.md

Show the posted message's link.
