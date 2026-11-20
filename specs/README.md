# The parts, and handing them to agents

One spec per part. Every spec starts with the same header, so an agent
(or a person) knows from the top of the file whether they can start:

- **Status:** open, in progress (branch), or built (date), per stage.
- **Agent:** a strong or a cheaper model, and what to have reviewed.
- **Depends on:** what must be merged first.
- **Touches:** the files and templates it changes, so parts running in
  parallel can be chosen not to collide.
- **Done when:** at the end of the part or of each stage.

## Index

Stages are separate hand-offs. "Next" means it can start now.

| Part | Stage | Status (2026-11-20) | Depends on | Agent |
|---|---|---|---|---|
| `core.md`, `access.md`, `api-cli.md` | | built | | |
| `notifications.md` | 1: mentions, levels, mails, digests | built | core | strong |
| `files.md` | 1: storage, attachments, downloads | built | core | strong |
| `todos.md` | 1: schedules, recurrence | built | core | cheaper |
| `todos.md` | 2: by due date, iCal | built | stage 1 | cheaper |
| `feed.md` | feed, history, bookmarks, links | built | core | cheaper |
| `files.md` | 2: messages (with pinning), folders, docs, files | built | notifications 1 | cheaper |
| `todos.md` | 3: long lists of completed to-dos | built | stage 2 | cheaper |
| `projects-overview.md` | favorites, activity order, cards | built | `feed.md` (bookmarks) | cheaper, review the client column |
| `glance.md` | excerpts, to-do indicators and peek, counts | built (message excerpts come with the board) | `feed.md`, notifications 1 | cheaper |
| `reactions.md` | to-dos and comments first | built | notifications 1 | cheaper |
| `notifications.md` | 1b: notified by default or only when tagged | built | notifications 1, files 2 | cheaper |
| `checkins.md` | | built | schedules, mails, attachments | cheaper |
| `notifications.md` | 2: replying by mail | built | notifications 1, check-ins | strong |
| `import-basecamp.md` | | open | every kind of item | cheaper |
| `collaboration.md` | | last | everything | strong |

`todos.md` stage 3, `projects-overview.md` and `glance.md` touch
different files ("Touches" in each) and can run at the same time.
`projects-overview.md`, `glance.md` and `files.md` stage 2 all use the
`|excerpt` filter: the first to merge adds it, the others use it.
`notifications.md` stage 1 changes `_todo.html` too: merge it before
starting `glance.md`.

## Handing a part to an agent

One part (or stage) per agent, in its own branch and worktree
(`git worktree add ../biwak-<part> -b <part>`). The brief can be short,
because the specs carry the rest:

> Build `specs/<part>.md` (stage N) in the worktree `../biwak-<part>`.
> Read `AGENTS.md`, `SPEC.md` and that spec first, and follow the
> checklist in `AGENTS.md`. Commit in small steps with tests; don't
> merge. Questions the spec doesn't answer: stop and list them, don't
> decide them. When done, update the spec's Status line and report
> what's built, what's left and the decisions you proposed.

Afterwards: review the branch (visibility tests above all), rebase it
on `main`, run `./runtests.sh` and `uvx prek run --all-files`, merge,
and update the index above.

## Keeping a part handable

- Everything an agent must decide is either in the spec or marked as a
  question for the user; values (limits, durations, wording) count.
- Name the files and functions to copy from (`biwak/items/`,
  `biwak/projects/`) instead of describing them.
- "Done when" lists tests, not intentions.
- A spec that grows past about 200 lines gets split into stages, each
  with its own "Done when".
