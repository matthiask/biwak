---
name: biwak-triage
description: Show what needs the user in Biwak (the project management tool for teams working with clients) with the `biwak` CLI, from the unread notifications in the lantern and the to-dos due soon, grouped into act, wait and keep an eye on. Use when the user asks what needs them, what's new, what to do next or today, to triage their notifications or inbox, or what they're waiting on in Biwak.
---

# What needs me in Biwak

The `biwak` CLI talks to Biwak (see `biwak --help`). If `biwak` isn't
installed or logged in, tell the user to run
`uv tool install "git+https://github.com/matthiask/biwak#subdirectory=cli"`
and `biwak login URL --write` (`--read` is enough for triage), which
authorizes `biwak` in the browser. If a command or option below is
missing, `uv tool upgrade biwak-cli`.

Triage reads, it changes nothing: listing the lantern doesn't mark
anything read. It marks entries read only when the user asks.

## 1. Read

Who the user is (their `id`), and today's date:

    biwak me --json

The lantern's unread entries, newest first, one per notification (an
item can have several):

    biwak lantern --unread --limit 200 --json

Each entry has `mentioned`, `bookmarked` and an `event`: its `action`
(`assigned`, `commented`, `created`, `completed`, …), the `actor`, the
`item` (`id`, `kind`, `title`, `url`, `visible_to_clients`), `data` (the
people assigned or mentioned, by ID: `assignees`, `mentioned`) and an
`excerpt` of the comment or message. If there are 200, say that there are more and work with these.

The user's open to-dos by due date, and those they assigned to others:

    biwak todos --mine --by-due --json
    biwak todos --assigned-by-me --by-due --json

Each to-do has `due_on`, `due_group` (`overdue`, `today`, `this_week`,
…), `assignees`, `project_name`, `list_title`, `url` and
`visible_to_clients`. Keep those overdue or due within the next 7 days
(`due_on` up to today plus 7); to-dos without a due date are left out.

Read an item only where the excerpt doesn't say enough to group it:

    biwak todos show <todo> --comments --json
    biwak messages show <message> --comments --json
    biwak docs show <doc> --comments --json

## 2. Group

Group by item, not by notification (several entries about one item are
one line: "3 comments by Ada and Bob"), in three groups:

- **Act:** what the ball is with the user for: entries mentioning them
  (`mentioned`), assigning them (`assigned` with their ID in
  `data.assignees`), questions or requests addressed to them in a comment
  or message, and their own to-dos overdue or due within 7 days, the
  overdue ones first.
- **Wait:** where the ball is with others: to-dos the user assigned to
  others (`--assigned-by-me`) that are overdue or due within 7 days,
  with who has them.
- **Keep an eye on:** the rest of the unread entries, briefly, newest
  first.

Each line with its link (the item's `url`), the project, what happened
and who did it, and the due date for to-dos. Mark what clients can see
with "[clients]". Don't guess what a comment wants: quote the excerpt
when it's unclear whether it's a question to the user.

Keep it short: a line per item, the act group first. Offer to open an
item, reply or do something about one; writing anything follows the
user's instructions (clients see what's marked "[clients]": say so and
let the user confirm before writing there).

## 3. Mark read, when asked

Only when the user asks, for the items they name, or all:

    biwak lantern --read <item>
    biwak lantern --all

`--read` marks an item's notifications read, its comments' too.
