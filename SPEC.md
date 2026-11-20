# Spec: Biwak

A self-hosted tool for teams working on projects with their clients:
to-do lists, message boards, docs and files, check-ins, an activity feed
and mail notifications, with clients seeing exactly what they're meant to
see. Modelled on what Basecamp does well, its focus on the essentials,
and deliberately not more.

This file describes what the app does and why, the shared model and the
decisions. The parts are specified in `specs/`, one file each, small
enough to hand to one agent. When a decision changes, update the spec in
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
6. Docs (rich text) and uploaded files in folders; later, docs edited
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
frontend bundle (rspack). German and English from the start.

Files go through Django's storage API: S3-compatible object storage by
default, other backends possible (`specs/files.md`).

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

The core has to exist before parts can be built in parallel; everything
depends on items, visibility, events and subscriptions.

1. **Core, one agent, in order:** `specs/core.md` (projects, items,
   lists, groups, to-dos, ordering), `specs/access.md` (visibility and
   login), events and subscriptions from `specs/notifications.md` (without
   mails yet).
2. **Then in parallel**, each in its own worktree and branch, merged one
   at a time:
   - `specs/todos.md`: assignees, recurrence, board view, the
     chronological list
   - `specs/notifications.md`: mails, levels, digests, replying by mail
   - `specs/checkins.md`
   - `specs/files.md`: messages' attachments, docs, uploads, folders,
     storage
   - `specs/feed.md`: activity feed, bookmarks, links
   - `specs/api-cli.md`: grows with each part, but its foundations
     (auth, conventions) come early
   - `specs/import-basecamp.md`
3. **Last and separately:** `specs/collaboration.md` (real-time editing,
   brings websockets and ASGI).

Before the first client gets a login, a separate review of the
visibility checks (another person, or a fresh agent given only the code
and `specs/access.md`).

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
