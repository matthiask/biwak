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

Open questions and decisions waiting for confirmation, across all
parts: `questions.md`.

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
| `search.md` | | built | every kind of item | cheaper |
| `api-cli.md` | gaps to the web, passkey offer, Google for staff | foundations built; agent skills postponed | | cheaper |
| `rule-widget.md` | one control for repeat rules | built | to-dos, check-ins | cheaper, review the round trips |
| `keyboard.md` | command palette (Ctrl+K), shortcuts | built 2026-11-21 | search | cheaper |
| `lantern.md` | the lantern (notifications in the app), live updates (built 2026-11-21 on `collaboration`) | built | collaboration (ASGI, Redis), notifications | strong |
| `project-colors.md` | a color per project | built | the accent palette | cheaper |
| `editor.md` | checklists and counts, the toolbar, pasting | built on branch `editor` | | cheaper |
| `archiving.md` | archiving projects and lists, findable; the importer completes archived to-dos | next (spec only for now) | the core, the importer | cheaper |
| `ui-round-1.md` | modals, quieter pages, to-do view mode, assignee picker, overdue | built | | cheaper |
| `organizations.md` | organizations as a model, domains, starting projects from them, partners | built; later: the people page grouped by organization | the core, the importer | cheaper |
| `connection.md` | the banner when offline, nothing lost silently | built | live updates, live editor | cheaper |
| `import-basecamp.md` | | built (2026-11-21) | every kind of item | cheaper |
| `api-cli.md` | agent skills | postponed (2026-11-21) | the importer | cheaper |
| `collaboration.md` | | built (branch `collaboration`, merged into `main` 2026-11-21, not deployed) | everything | strong |
| `people.md` | 1: profile images, the person's page | built 2026-11-21 (branch `people`) | `organizations.md` | cheaper, review the image's visibility |
| `people.md` | 2: choosing from drawn images | later | stage 1, the drawings | cheaper |
| `ui-round-2.md` | A–C built; D: projects page and color picker; E: sign-in and sessions; F: same first names | built | lantern, people 1 | cheaper |
| `subscribers.md` | assigned means subscribed; adding others, telling them now | built | ui-round-2 B, modals, lantern | cheaper, visibility tests |
| `ui-round-3.md` | "My to-dos" by project or due date, no list filter, filters apply themselves | built | todos 2 | cheaper |
| `ui-round-4.md` | phones: headers, to-do rows, toolbar, small things; feedback round 4 (sign out, visibility modal, feed conversations) | built 2026-11-21 (`ui4-layout`, `ui4-behavior`) | ui-round-3, ui-round-2 D | cheaper |
| `ui-round-5.md` | feedback round 5: cards on to-dos and docs, the project's to-dos linked, filter buttons, assigned by me | built 2026-11-21 (`ui5`) | ui-round-4 | cheaper |
| `ui-round-6.md` | a combobox for long people selects, inviting several people to several projects, invitations visible, subscribing is the switch | next | organizations, subscribers | cheaper (A), review B and C |
| `ui-round-7.md` | files as tiles with "..", folder modals, ordering per folder, drag and drop and selecting several, new docs opening the editor | next | files, doc-titles, subscribers | strong, review visibility |
| `activation.md` | activating imported people and deactivating people who left: pages, API, CLI, admins only | next | ui-round-6, sso | cheaper, review deactivating |
| `doc-titles.md` | a doc's title is its first line (a heading or the first text), no title form below the editor | next | files, collaboration | cheaper |
| `deploy-checklist.md` | what the next deploy brings, what to set up before and after, what to check | for the next deploy | | |
| `feed.md` | links: projects only, quieter ("Links", changed 2026-11-21) | built 2026-11-21 (`links`) | ui-round-4 | cheaper |
| `lantern.md` | reading by acting: completing, editing, commenting, reacting read the item's notifications for the actor | built 2026-11-21 (`reading`) | lantern | cheaper |
| `dashboard.md` | Home at `/`: what needs me (to-dos due, check-ins, waiting on others), recent updates, my projects, bookmarks, links; projects move to `/projects/` | built 2026-11-21 (`home`) | ui-round-5, `feed.md` links, `lantern.md` reading by acting | cheaper, review the visibility tests |
| `help.md` | help pages from `docs/` like Governance's, the shortcuts list moves there from settings, links to the help | built 2026-11-21 (`help`), the texts read by the user | `dashboard.md` | cheaper, the texts read by the user |
| `celebrations.md` | small celebrations (completing a to-do, the last of a list) and animations | built | | cheaper |
| `timeline.md` | the to-do's comments with what happened between them (completed, moved, assigned, due date, title, visibility, trash) | built | | cheaper, review visibility |
| `pwa.md` | installable as an app (manifest, icons), no push and no offline yet | built | | cheaper |
| `mail-sending.md` | sending through Resend, an outbox with retries, bounces and complaints | built 2026-11-21 (`mail-sending`), not deployed | | strong |
| `sso.md` | sign-in per organization: codes and passkeys, SSO allowed or required; Google Workspace, Entra ID prepared | next | `organizations.md` | strong, review the checks |

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
