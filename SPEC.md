# Spec: Biwak

A self-hosted tool for teams working on projects with their clients:
to-do lists, message boards, docs and files, check-ins, an activity feed
and mail notifications, with clients seeing exactly what they're meant to
see. Modelled on what Basecamp does well, its focus on the essentials,
and deliberately not more.

This file describes what the app does and why, the shared model and the
decisions. The parts are specified in `specs/`, one file each, small
enough to hand to one agent; `specs/README.md` lists them with their
status. When a decision changes, update the spec in the same commit and
date the decision ("decided 2026-11-20"), so later sessions don't reopen
it.

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
6. Docs (Markdown, edited together in real time) and uploaded files in
   folders.
7. Check-ins: questions asked on a schedule, answers collected with
   comments.
8. Client access per list, folder, message or doc.
9. Subscriptions to any item, mail notifications with sensible levels,
   replying by mail.
10. Activity feed per project, per person and across everything.
11. Bookmarks, and links to outside tools on projects (not on items).
12. API, CLI, agent skills.
13. An importer for Basecamp 4 accounts.
14. Public links: one item shown read only to people outside, for at
    most 30 days (`specs/public-links.md`).

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
  subscriptions and bookmarks point at items but aren't items.
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
- **Bookmark** (person, item or project). **Link** (project, URL,
  title, kind; not on items since 2026-11-21).

Customer visibility is a property computed from the item and its
containers, checked in one place (`specs/access.md`).

## Glossary

- **Staff**: members of the organization running the installation.
- **Partner**: staff outside the own organization (freelancers, other
  agencies); sees only the projects they're members of
  (`specs/organizations.md`).
- **Client**: a person outside the organization, invited to projects.
  Sees only what is visible to clients.
- **Visible to clients**: the switch on containers and some items; shown
  with a bright badge on rows and a tab at the window's edge on pages
  (`specs/access.md`).
- **Container**: a list or a folder.
- **Group**: a heading inside a list; to-dos point at it, ordered within
  it. Shown as columns in the board view.

## Build order

The core came first; every part since builds on it and on the shared
foundations (mentions and mails, storage and attachments, schedules).
What's built and what's open is in `specs/README.md`. The German
translation is `specs/languages.md` (started 2026-11-22; texts are
marked with `gettext`; the wording of mails, the editor and the lantern
is reviewed with it).

Each part adds its API endpoints and CLI commands (`api-cli.md`) in the
same branch. `AGENTS.md` has the checklist every part follows.

## Backlog

Nothing waiting for a spec at the moment. What's deliberately "later"
stays in its part's spec: webhooks and agent skills (`api-cli.md`),
browser notifications (`lantern.md`), drawn profile images
(`people.md`). Give a new wish a spec (or a section in one) before
building it.

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
- 2026-11-21: Sign-in per organization (`specs/sso.md`): codes by mail
  and passkeys (django-allauth), Google Workspace or Microsoft Entra ID
  allowed, or required for organizations whose IdP manages their people;
  the own organization allows Google. No passwords. (Replaces 2026-11-20:
  codes and passkeys for everybody, Google optional for staff.)
- 2026-11-21: Passkeys are a way in, not a second factor; authenticator
  apps are an optional second factor, without recovery codes (a reset
  instead); organizations may require a second factor
  (`specs/two-factor.md`).
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
- 2026-11-20: Reply tokens valid 6 months; files up to 100 MB; a doc
  version per 10 minutes or author; answers to check-ins as one summary
  mail by default; links internal by default; previews made on first
  request.
- 2026-11-20: No reminders for missed check-ins, and no skipping
  (`specs/checkins.md`).
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
- 2026-11-21: The lantern (named so, not "Hey!"): notifications in the
  app (an icon with a count, a page), mail optional (each, digest,
  none), what's read in the app not mailed; item pages, lists and the board update live, reactions
  included, changes appearing in place; the websocket only says what
  changed, content comes through the permission-checked views
  (`specs/lantern.md`). Browser notifications later.
- 2026-11-21: A command palette (Ctrl+K and "/") with jumps and actions,
  search being one of them, and single-key shortcuts inside pages that a
  setting turns off (`specs/keyboard.md`).
- 2026-11-20: Reactions: quick emoji (32 since 2026-11-21) and short
  texts (40 characters), telling only the author, collected into the
  next mail or the digest (`specs/reactions.md`).
- 2026-11-20: Docs are edited live with Yjs and CodeMirror; the server
  side is Channels with pycrdt inside Django, not a Hocuspocus service
  (the spike, `specs/collaboration.md`). No doc locks (2026-11-21), at
  most a heads-up; docs can be made read-only by staff.
- 2026-11-21: People have a mark: their profile image (cut to a 256 pixel
  square, WebP, served only to whoever may know the person) or their
  initials on a palette color chosen from the ID; a page per person with
  the projects in common. Basecamp's images are imported, those it
  generated skipped (`specs/people.md`).
- 2026-11-21: Only projects and lists are archived; to-dos are
  completed, nothing smaller is archived (`specs/archiving.md`).
- 2026-11-21: Home at `/` shows what needs the person and where things
  are going on; the projects page moves to `/projects/`
  (`specs/dashboard.md`).
- 2026-11-21: Subscribing is the switch: a subscriber hears about
  everything on the item; levels (projects and lists only) decide who
  gets subscribed automatically (`specs/notifications.md`).
- 2026-11-21: Outgoing mail goes through an outbox in the app and
  Resend's API (`specs/mail-sending.md`).
- 2026-11-21: View choices (groupings, orderings) and filters are query
  parameters remembered in the browser, never fields on `User`
  (`specs/ui.md`, "Filters and view choices").
- 2026-11-22: Nobody leaves a project: own staff remove people,
  themselves included, after a question; clients and partners can't
  remove themselves, so that they can't get around the organization's
  decisions about who works on a project, and notifications cover not
  hearing about it (`specs/organizations.md`).
