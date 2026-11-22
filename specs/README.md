# The parts

One spec per part: what it does, the decisions in force and where it
lives in the code. Open questions go to the user and the answer into
the part's spec (`AGENTS.md`). The
rules every page follows: `ui.md`; the user's feedback notes, round by
round: `ui-feedback.md`; decisions made without asking, for the user to
confirm: `decisions-to-confirm.md`.

| Part | Status | What |
|---|---|---|
| `core.md` | built | projects, items, lists, groups, ordering |
| `ui.md` | built | the rules every page follows: modals, quiet pages, filters, phones, motion |
| `access.md` | built | client visibility (one function decides what clients see) and sign-in: the ways in, the sign-in page, sessions |
| `api-cli.md` | built; agent skills postponed | the API's conventions, the CLI |
| `notifications.md` | built | events, subscribing is the switch, mentions by short name, levels on projects and lists, mails and digests, replying by mail |
| `files.md` | built | attachments, the message board, folders as tiles with ordering, drag and drop and uploading several, docs (title from the first line, versions, drafts), files |
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
| `lantern.md` | built | notifications in the app counted by item, reading by acting, live updates |
| `keyboard.md` | built | the command palette, shortcuts, the settings page, the palette of colors |
| `project-colors.md` | built | a color per project |
| `editor.md` | built | checklists, the toolbar, pasting, ticking while someone edits |
| `archiving.md` | built | archiving projects and lists, nothing smaller |
| `connection.md` | built | the offline banner, nothing lost silently |
| `organizations.md` | built | organizations, externals, the People page |
| `people.md` | built, drawn marks too | the mark, profile images, names, the person's page |
| `subscribers.md` | built | assigned means subscribed, adding others, telling them now |
| `dashboard.md` | built | Home: what needs me, recent updates, my projects |
| `help.md` | built | the help pages from `docs/` |
| `celebrations.md` | built | small celebrations and animations |
| `handover.md` | built | when somebody leaves: assignments stay, assigning, moving and dating several to-dos, all projects for admins |
| `timeline.md` | built | what happened between a to-do's comments |
| `pwa.md` | built | installable as an app |
| `mail-sending.md` | built | the outbox and sending through Resend, bounces |
| `sso.md` | built | sign-in per organization, single sign-on allowed or required |
| `activation.md` | built | people: inviting several at once, invitations, activating, deactivating, resets |
| `doc-titles.md` | built | pointer: a doc's title is its first line, now in `files.md` |
| `two-factor.md` | built | passkeys as a way in, authenticator apps as an optional second factor, organizations requiring one |
| `public-links.md` | built | read-only links to one item for people outside, expiring after 1 to 30 days |
| `teams.md` | built | named sets of people, expanded into their members when assigning, subscribing or mentioning |
| `rich-editor.md` | built | one rich-text editor (ProseMirror) for every text, live docs included, still storing Markdown |
| `languages.md` | built | German, a language per person, everything following it |
| `quiet-hours.md` | built | quiet hours for mails, out of office (one time zone) |
| `start-dates.md` | built | start dates on to-dos, hidden from current work until they start |
| `lists-across-projects.md` | built | copying lists, moving top-level items to another project |
| `todos-from-text.md` | built | dropping or pasting a Markdown list onto a to-do list: headings become groups |
| `templates.md` | built (decisions to confirm in the spec) | projects and lists started from templates kept in the app |
| `cli-style.md` | built (0.60.0) | the CLI in the style of gov and wb: one plural group per thing, verbs as subcommands |
| `web-push.md` | open | push notifications on phones and desktops |
| `forwarding.md` | built | one address to forward mails to, filed as messages or to-dos |

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
