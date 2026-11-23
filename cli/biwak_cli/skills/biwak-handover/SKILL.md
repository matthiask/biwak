---
name: biwak-handover
description: Hand over somebody's open to-dos in Biwak (the project management tool for teams working with clients) with the `biwak` CLI when they leave or are away, project by project, with new assignees, dates and lists the user confirmed, through the bulk commands. Use when someone leaves the team, goes on holiday, parental leave or sick leave, or the user wants to reassign, redistribute or take over a person's to-dos in Biwak.
---

# Handing over somebody's to-dos in Biwak

The `biwak` CLI talks to Biwak (see `biwak --help`). If `biwak` isn't
installed or logged in, tell the user to run
`uv tool install "git+https://github.com/matthiask/biwak#subdirectory=cli"`
and `biwak login URL --write`, which authorizes `biwak` in the browser.
Changing to-dos needs `--write`; if `biwak` answers that the token only
allows reading, ask the user to log in with `--write` instead of working
around it. `biwak todos --assignee` needs `biwak` 0.63.0 or later:
`uv tool upgrade biwak-cli`.

The skill proposes, the user decides: nothing changes before the user
confirmed a project's changes, one project at a time.

## 1. Who, and why

Find the person (active people, then those who left) and ask what's
happening, if the user hasn't said: leaving for good, or away until a
date.

    biwak me --json
    biwak people --json
    biwak people --left --json

## 2. Their open to-dos, per project

    biwak todos --assignee <person> --json

The to-dos come by project, list and group, each with `due_on`,
`starts_on`, `assignees` (with who assigned them), `url` and
`visible_to_clients`. Show them per project with their links: how many,
which are overdue or due soon, which have other assignees too, which
have no due date.

Admins also see projects where open to-dos are left with nobody active:

    biwak projects --all --inactive-todos

## 3. Propose, one project at a time

For each project, who can take over: the project's members, with who's
away (`away_until`):

    biwak members --project <project> --json

Propose, per project:

- **New assignees** per to-do or for groups of to-dos (by list,
  usually), from the members who aren't away; ask the user who knows
  the work, don't guess from names. Leaving: the person comes off
  the to-dos (`--replace`). Away: ask whether the new person is added
  (the to-dos come back to the person later) or replaces them.
- **Dates** only where the user wants them changed: a new due date for
  several (`--due`) or moved by some days (`--shift`), e.g. the length
  of an absence for to-dos that wait for the person.
- **Another list** only where the user wants one (`biwak lists
  --project <project> --json` lists them).

Say which to-dos clients can see (`visible_to_clients`): clients see
who's assigned and the new dates. Get the user's confirmation for the
project before writing.

## 4. Apply, after the user confirmed the project

The bulk commands change all the to-dos given at once (all or nothing),
record one event, and tell each new assignee once:

    biwak todos assign <todo> <todo> --to <person> --replace --json
    biwak todos dates <todo> <todo> --due <date> --json
    biwak todos dates <todo> <todo> --shift <days> --json
    biwak todos move <todo> <todo> --list <list> --json

`--replace` takes off **all** current assignees, not only the person
handed over: for to-dos with others assigned too, run them separately
and repeat those others in `--to` (`--to` is repeatable). Without
`--replace` the new people are added. An error names what's wrong (a
person who isn't a member, a to-do gone); nothing was changed then.
Moving to a list of another project needs `--confirm` when people are
added or dropped: show the user who first.

Show what changed with the links, then go on with the next project.

## 5. Afterwards

- **Leaving:** point the user to deactivating the person in Biwak (the
  person's page, "Deactivate…"; `biwak people deactivate <person>` does
  the same; staff deactivate clients, admins also staff), only when the
  user asks for it. It ends their
  access and keeps their assignments, so what wasn't handed over can
  still be found (`biwak todos --assignee <person>`).
- **Away:** point to the away setting, which holds their mails and shows
  them as away: the person sets it (`biwak away --until <date> --note
  <note>`), an admin can for them (`biwak away --person <person> --until
  <date>`).
