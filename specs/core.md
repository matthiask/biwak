# Core: projects, items, lists, groups, to-dos

Everything else builds on this. Built first, by one agent, before any part
in parallel. See `SPEC.md` for the model overview.

## Projects

- Name, description, archived. Members: people with a role in the project
  (staff or client). Staff can be members of any project they're added to;
  admins see all projects.
- A project has one message board, one root folder and any number of
  lists. Project page: the lists, the latest messages, docs and files,
  links, and the project's activity.
- Archiving a project hides it from lists and the feed; everything stays
  readable.

## Items

One table for the shared parts, typed details where needed (a to-do's due
date, a file's blob). Choose between one table with nullable fields,
multi-table inheritance or a generic item plus one-to-one detail tables;
whatever keeps queries for "everything in this project, visible to this
person, newest first" simple and fast. Write the choice into this file.

Shared fields: project, parent, type, position (within the parent),
title, content (rich text, stored as sanitized HTML, see below), creator,
created/updated, status (active, archived, trashed), visible to clients
(only meaningful where `access.md` says so).

Allowed parents per type are enforced in the model, not only in forms:

| Type | Parent |
| --- | --- |
| list | project (no parent item) |
| group | list |
| to-do | list or group |
| message | project (the message board) |
| folder | project root or folder |
| doc, file | project root or folder |
| check-in question | project |
| check-in answer | check-in question |

Trashing is soft and recoverable for 30 days; children follow their
parent. Archiving keeps items readable but out of the way.

## Rich text

One editor for to-dos' notes, messages, comments and docs: Markdown-ish
shortcuts, links, lists, headings, code, images and file attachments,
mentions. Stored as sanitized HTML (an allow-list), rendered as is; a
plain text / Markdown version is derived for mails, search, the API and
agents. The API accepts Markdown and converts it.

## Lists, groups and ordering

- A list is one ordered sequence of to-dos and group headings. A to-do
  belongs to the group heading above it; to-dos above the first heading
  are ungrouped.
- Dragging a group moves the heading with its to-dos as a block. Dragging
  a to-do across a heading moves it into that group. Dragging a to-do to
  another list moves it there (keyboard alternatives for all of it).
- Completed to-dos leave the sequence and show below the list, newest
  first, collapsed.
- Positions: integers with gaps, renumbered when needed, or fractional
  ranks; moves must be one request and safe against concurrent moves
  (row locks on the list).
- Lists themselves are ordered on the project page and can be archived.
- A list has a description but no comments.

## To-dos

Title, notes (rich text), assignees, due date (optional start date),
completed (when, by whom), comments, attachments. Assignees, recurrence,
the board view and the chronological list are in `todos.md`; the core
only needs the fields.

## Tests

Model constraints (allowed parents, ordering after every kind of move,
concurrent moves), trashing and restoring with children, archiving.
