# Spec: Biwak

A self-hosted tool for teams working on projects with their clients:
to-do lists, message boards, docs and files, check-ins, an activity feed
and mail notifications, with clients seeing exactly what they're meant to
see. Modelled on what Basecamp does well, its focus on the essentials,
and deliberately not more.

This file describes what the app does and why, the shared model and the
decisions. The parts are specified in `specs/`, one file each, small
enough to hand to one agent; `specs/README.md` lists them with their
status and dependencies and says how to hand one to an agent. When a decision changes, update the spec in
the same commit and date the decision ("decided 2026-11-20"), so later
sessions don't reopen it.

## Principles

- **Few concepts.** Lists of to-dos, messages, docs, files, check-ins.
  No boards as a separate concept, no issue tracker, no custom fields, no
  workflows. A feature that needs configuration before it's useful is a
  feature we don't want.
- **Clients are first-class.** Teams discuss to-dos with their clients;
  much of the conversation is visible to them. Visibility must be
  impossible to get wrong by accident (`specs/access.md`).
- **Mail is a full client.** Many people, clients above all, never open
  the app: notifications carry the full content, and replying to a mail
  posts a comment (`specs/notifications.md`).
- **API first.** The web interface is one client among others; the API,
  a CLI and agent skills cover everything the interface does
  (`specs/api-cli.md`).
- **Boring technology.** Django, PostgreSQL, server-rendered pages with
  htmx; JavaScript only where interaction needs it (drag and drop, the
  editor).

## Scope

In scope:

1. Projects with members: staff and clients. All-access projects (every
   staff member can see them) or limited ones (members only).
2. To-do lists with groups, reorderable, to-dos with several assignees,
   due dates, recurrence, comments. Lists can be subscribed to.
3. A board view: a list shown with its groups as columns.
4. A chronological list of to-dos by due date, filterable, per project
   and across projects ("my to-dos").
5. Message boards with comments.
6. Docs (Markdown) and uploaded files in folders; later, docs edited
   together in real time.
7. Check-ins: questions asked on a schedule, answers collected with
   comments.
8. Client access per list, folder, message or doc.
9. Subscriptions to any item, mail notifications with sensible levels,
   replying by mail.
10. Activity feed per project, per person and across everything.
11. Bookmarks, and links to outside tools on projects and items.
12. API, CLI, agent skills.
13. An importer for Basecamp 4 accounts.

Out of scope on purpose:

- **Chat** and direct messages: teams have other tools for that.
- **Schedule / calendar** per project: the chronological to-do list
  covers due dates; an iCal feed of them is cheap.
- **To-dos outside lists**: every to-do belongs to a list.
- **Comments on lists, groups and folders**: they turn a list into a
  to-do of its own; discussion belongs on to-dos and messages.
- **Hill charts, doors, time tracking, invoicing, planning**: other
  tools do that; link to them.
- **Forwarding arbitrary mails into a project**: an agent with the CLI
  can turn a mail into a to-do or a message. Replying to notification
  mails is in scope.

## Stack

A separate project built from the code and conventions of
[Governance](https://github.com/feinheit/governance) (itself built from
[Workbench](https://github.com/matthiask/workbench)) by copying, not
depending on it: Django, PostgreSQL, a reduced `User`, django-ninja for
the API, the audit log trigger, the page layout (light and dark mode),
htmx, sortable lists, mentions, modals, daily and hourly tasks, one
frontend bundle (rspack). English first, German at the end of the build
(texts are marked for translation from the start).

Files go through Django's storage API: local disk in development, an
S3-compatible bucket when deployed, chosen by settings
(`specs/files.md`). Mail goes out and comes in through Resend
(`specs/notifications.md`).

No real data in this repository: tests and examples use made-up projects,
people and clients.

## Model

Almost everything is an **item** in a project, like Basecamp's
recordings. A few generic building blocks then cover most of the scope;
`specs/core.md` has the details.

- **Project**: name, description, members (staff and clients),
  all-access or limited, archived.
- **Item** (delegated types): one table with the shared fields
  (project, parent, kind, position, effective visibility, status,
  creator, timestamps), and a one-to-one detail model per kind for the
  rest (`Todo`, `Message`, `Doc`, `Upload`, …). Kinds: list, to-do,
  message, folder, doc, file, check-in question, check-in answer.
  Everything other features point at is an item; comments, events,
  subscriptions, bookmarks and links point at items but aren't items.
- **Tree**: items form a shallow forest per project. Only folders nest
  without limit; everything else has a fixed parent kind (a to-do's
  parent is its list, an answer's its question).
- **Group**: not an item and not a parent. A to-do has a nullable group
  (a heading within its list) and a position within it.
- **Containers**: lists and folders. Their children inherit visibility
  from them; the effective visibility is stored on each item.
- **Comment** on to-dos, messages, docs, files and check-in answers only.
- **Subscription** (person, item): to the item and, for containers, to
  new children. Automatic for the author, assignees and people mentioned;
  cancellable any time.
- **Event** (who, what, which item, when): one table feeds the activity
  feed and the notifications (events × subscriptions).
- **Bookmark** (person, item). **Link** (project or item, URL, title,
  kind).

Customer visibility is a property computed from the item and its
containers, checked in one place (`specs/access.md`).

## Glossary

- **Staff**: members of the organization running the installation.
- **Client**: a person outside it, invited to projects. Sees only what is
  visible to clients.
- **Visible to clients**: the switch on containers and some items; shown
  with a bright badge and banner everywhere.
- **Container**: a list or a folder.
- **Group**: a heading inside a list; to-dos point at it, ordered within
  it. Shown as columns in the board view.

## Build order

The core has to exist before anything else; some parts need pieces of
others, so the order below is fixed. Each step is one branch, merged
before the steps that depend on it. `AGENTS.md` has the checklist every
part follows; each spec has a "Done when" list and says whether it suits
a cheaper model ("Agent").

1. **Core** (done 2026-11-20): `core.md`, `access.md`, events and
   subscriptions from `notifications.md`, the API foundations from
   `api-cli.md`.
2. **Shared foundations, one after another**, because later parts build
   on them:
   1. `notifications.md`, stage 1: mentions, levels, outgoing mails,
      digests.
   2. `files.md`, stage 1: storage, uploads, attachments in texts,
      downloads.
   3. `todos.md`, stage 1: schedules (`biwak/schedules.py`) and
      recurring to-dos.
3. **In parallel:**
   - `todos.md`, stage 2: the list by due date, the iCal feed.
   - `files.md`, stage 2: message board, folders, docs with versions,
     file pages, previews.
   - `feed.md`: activity feed, item history, bookmarks, links.
   - `todos.md`, stage 3: long lists of completed to-dos.
   - Once `feed.md` is merged: `projects-overview.md` (favorites,
     ordering by activity, cards) and, after `notifications.md` stage 1
     too, `glance.md` (more content without opening every page).
   - Once `notifications.md` stage 1 is merged: `reactions.md` (to-dos
     and comments; later parts add their kinds).
4. `checkins.md` (needs schedules, mails and attachments).
5. `notifications.md`, stage 2: replying by mail, to comments and to
   check-in questions (a strong model: sender checks and mail loops are
   easy to get subtly wrong).
6. `search.md` (decided 2026-11-20), and the gaps to the web from
   `api-cli.md` (API and CLI for projects and members, moving to-dos,
   the passkey offer, Google sign-in for staff only).
7. `import-basecamp.md` (needs every kind of item), then the agent skills
   (`api-cli.md`).
8. **Last and separately:** `collaboration.md` (real-time editing,
   brings websockets and ASGI; built 2026-11-20, not deployed), then the
   German translation.

Each part adds its API endpoints and CLI commands (`api-cli.md`) in the
same branch.

Before the first client gets a login, a separate review of the
visibility checks (done 2026-11-20, its findings fixed) (another person, or a fresh agent given only the code
and `specs/access.md`).

## Backlog

Wanted, not specified in detail yet and not in the build order; give
each a spec (or a section in one) before building it.

- **Sending through Resend** (added 2026-11-21): mail goes out through
  the cluster's postfix and Gmail today (`biwak@feinheit.ch`, passing
  SPF and DKIM); Resend only receives replies. Moving sending to Resend
  (`EMAIL_URL` to its SMTP, a From domain verified there, e.g.
  `biwak.feinheit.app`) as decided for both directions, when there's a
  reason to.

## Decisions

- 2026-11-20: Separate app, not part of Governance; copy its code and
  conventions.
- 2026-11-20: No boards as a separate concept; a list with its groups as
  columns is enough, no deeper structure.
- 2026-11-20: Recurring to-dos create the next one when the current one is
  completed, never a stack of open copies.
- 2026-11-20: Several assignees per to-do; completing it completes it for
  all of them.
- 2026-11-20: No comments on lists, groups or folders; no to-dos outside
  lists.
- 2026-11-20: No internal comments on items visible to clients.
- 2026-11-20: No single sign-on as the only way in; login by mail code
  or passkey (django-allauth) for everybody, Google sign-in optional for
  staff.
- 2026-11-20: Replying to notification mails posts a comment, from the
  start.
- 2026-11-20: Check-ins are in scope, the project schedule isn't.
- 2026-11-20: Projects are all-access (all staff) or limited (members
  only); clients only ever see projects they're members of. Joining a
  project late subscribes to nothing that exists already.
- 2026-11-20: Texts are stored as Markdown.
- 2026-11-20: Items as delegated types (shared `Item` plus detail models);
  groups are a foreign key on to-dos, not tree nodes; django-tree-queries
  for subtree operations; effective visibility stored per item, so the
  visibility check needs no recursive query.
- 2026-11-20: Translations postponed to the end; texts are marked with
  `gettext` but there's no German catalog until then.
- 2026-11-20: Resend sends and receives mail: it reports SPF, DKIM and
  DMARC results for incoming mail, which the sender check of replies
  needs; Brevo's inbound parsing doesn't. Providers stay behind one
  interface.
- 2026-11-20: Files on local disk by default, an S3-compatible bucket
  through settings; the first deployment uses the bucket.
- 2026-11-20: One list of message categories for the installation,
  edited by admins.
- 2026-11-20: Notification mails about 2 minutes after the last change
  to an item (merging quick edits), digests at 07:00.
- 2026-11-20 (proposed when tightening the specs, change them there if
  wrong): reply tokens valid 6 months; files up to 100 MB; a doc
  version per 10 minutes or author; doc locks expire 5 minutes after
  the last renewal; answers to check-ins as one summary mail by
  default; links internal by default; previews made on first request.
- 2026-11-20: No reminders for missed check-ins (replaces the reminder
  after 24 hours proposed above).
- 2026-11-20: Favorites are bookmarked projects, first on the projects
  page; projects ordered by activity (stored per project, a separate
  time for clients) or by name, switchable and remembered per person;
  projects as cards (`specs/projects-overview.md`).
- 2026-11-20: Messages are pinned for everybody, by staff only, any
  number (`specs/files.md`).
- 2026-11-20: More content on overview pages as small signals, short
  excerpts and a peek on demand, never settings (`specs/glance.md`).
- 2026-11-20: Replies by mail are posted when the receiving server
  reports DMARC or (aligned) DKIM as passed; SPF alone isn't enough,
  since Resend doesn't report its alignment (`specs/notifications.md`).
- 2026-11-20: Repeat rules are edited with one widget (frequency,
  interval, weekdays, monthly by day or nth weekday, yearly), no presets
  or raw RRULE in the forms, the description instead of a preview
  (`specs/rule-widget.md`); the API and CLI keep RRULEs and presets.
- 2026-11-21: GitHub's task lists in all texts, tickable in place and
  counted on rows; a small toolbar on every Markdown field; pasting rich
  text keeps bold, emphasis, links and lists (`specs/editor.md`).
- 2026-11-21: An accent color per person in the settings (the clients'
  amber reserved), and a color per project set by staff
  (`specs/keyboard.md`, `specs/project-colors.md`).
- 2026-11-21: The lantern (named so, not "Hey!"): notifications in the app (an icon with a count, a
  page), mail optional (each, digest, none), what's read in the app not
  mailed; item pages, lists and the board update live, reactions
  included, changes appearing in place; the websocket only says what
  changed, content comes through the permission-checked views
  (`specs/lantern.md`). Browser notifications later.
- 2026-11-21: A command palette (Ctrl+K and "/") with jumps and actions,
  search being one of them, and single-key shortcuts inside pages that a
  setting turns off (`specs/keyboard.md`).
- 2026-11-20: Reactions: 24 quick emoji and short texts (40
  characters), telling only the author, collected into the next mail
  or the digest (`specs/reactions.md`).
- 2026-11-20: Docs are edited live with Yjs and CodeMirror; the server
  side is Channels with pycrdt inside Django, not a Hocuspocus service
  (the spike, `specs/collaboration.md`). The doc locks are gone; docs can
  be made read-only by staff.
