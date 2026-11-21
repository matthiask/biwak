# The parts

One spec per part: what it does, the decisions in force and where it
lives in the code. Open questions across all parts: `questions.md`. The
user's own feedback notes: `ui-feedback.md`.

| Part | Status | What |
|---|---|---|
| `core.md` | built | projects, items, lists, groups, ordering; conventions shared by every page |
| `access.md` | built | client visibility (one function decides what clients see) and sign-in: the ways in, the sign-in page, sessions |
| `api-cli.md` | built; agent skills postponed | the API's conventions, the CLI |
| `notifications.md` | built | events, subscriptions, mentions, levels, mails and digests, replying by mail |
| `files.md` | built | attachments, the message board, folders, docs with versions, files |
| `todos.md` | built | assignees, the board, the to-do's page, recurrence, the to-dos page, the calendar feed |
| `rule-widget.md` | built | one control for repeat rules |
| `feed.md` | built | the activity feed, item history, bookmarks, project links |
| `projects-overview.md` | built | the projects page: favorites, ordering by activity, cards |
| `glance.md` | built | signals, excerpts and the peek instead of opening every page |
| `reactions.md` | built | emoji and short texts on items and comments |
| `checkins.md` | built | questions on a schedule, answers, summaries |
| `search.md` | built | full-text search across projects |
| `import-basecamp.md` | built | importing Basecamp 4 projects |
| `collaboration.md` | built | docs edited together live (Yjs, Channels) |
| `lantern.md` | built | notifications in the app, live updates, reading by acting |
| `keyboard.md` | built | the command palette, shortcuts, the settings page, the palette of colors |
| `project-colors.md` | built | a color per project |
| `editor.md` | built | checklists, the toolbar, pasting, ticking while someone edits |
| `archiving.md` | built | archiving projects and lists, nothing smaller |
| `connection.md` | built | the offline banner, nothing lost silently |
| `organizations.md` | built | organizations, partners, the People page |
| `people.md` | built; drawn images postponed | the mark, profile images, names, the person's page |
| `subscribers.md` | built | assigned means subscribed, adding others, telling them now |
| `dashboard.md` | built | Home: what needs me, recent updates, my projects |
| `help.md` | built | the help pages from `docs/` |
| `celebrations.md` | built | small celebrations and animations |
| `timeline.md` | built | what happened between a to-do's comments |
| `pwa.md` | built | installable as an app |
| `mail-sending.md` | built | the outbox and sending through Resend, bounces |
| `sso.md` | built | sign-in per organization, single sign-on allowed or required |
| `activation.md` | built | people: inviting several at once, invitations, activating, deactivating, resets |
| `doc-titles.md` | built | a doc's title is its first line |
| `two-factor.md` | built | passkeys as a way in, authenticator apps as an optional second factor, organizations requiring one |
| `ui-round-1.md` … `ui-round-6.md` | built | feedback rounds: where their decisions live now |
| `ui-round-7.md` | open | files as tiles, folder modals, ordering, drag and drop, new docs opening the editor |

## Writing a spec for a new part

Start with **Status** (open, built with the date), **Depends on** and,
for parallel work, **Touches** (files and templates it changes). Put
everything an agent must decide in the spec or mark it as a question for
the user; values (limits, durations, wording) count. Name the code to
copy from instead of describing it. End with **Done when**: tests, not
intentions.

Hand it to an agent in its own branch and worktree (`git worktree add
../biwak-<part> -b <part>`):

> Build `specs/<part>.md` in the worktree `../biwak-<part>`. Read
> `AGENTS.md`, `SPEC.md` and that spec first, and follow the checklist
> in `AGENTS.md`. Commit in small steps with tests; don't merge.
> Questions the spec doesn't answer: stop and list them, don't decide
> them. When done, update the spec's Status line and report what's
> built, what's left and the decisions you proposed.

**Once built,** the spec keeps what the part does and the decisions in
force; the build's story (branches, "Done when", resolved questions,
bug histories) goes, git keeps it (decided 2026-11-21).
