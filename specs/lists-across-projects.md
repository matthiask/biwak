# Copying lists, moving across projects

Copying a to-do list (into the same or another project) and moving
top-level items to another project. Decided with the user 2026-11-22.
Project templates are left to an agent skill that sets up projects
through the CLI (`api-cli.md`, "Agent skills").

**Status:** open.

Depends on: `core.md` (moving, "Move to…"), `access.md` (visibility,
showing to clients asks first), `todos.md`, `files.md`,
`notifications.md` (subscriptions), `feed.md`, `start-dates.md`,
`archiving.md`, `public-links.md`.

## Copying a list

- **"Copy…"** in a list's "More" menu and the palette: a modal with
  the target project (the combobox of projects the person can open and
  create lists in; the same project preselected), the new title and
  the dates (below). The title is the list's own; only when the target
  project already has a list of that name (ignoring case) it gets
  " (copy)", then " (copy 2)" and so on (decided 2026-11-22).
- **The open work** (decided 2026-11-22): title, description, groups
  (in order), open to-dos in order with their notes and checklists
  (unticked as they are). Not completed to-dos, comments, history,
  events, subscribers, reactions, public links.
- **Assignees** who are members of the target project stay; others
  are left out (the modal says who: "Cleo isn't in Website: left
  unassigned").
- **Dates:** "Keep", "Move by N days" (due and start dates together),
  or "Remove"; recurrence rules stay.
- **Visibility** is the target's: the copy is internal unless "Visible
  to clients" is ticked in the modal (staff only), which asks first like
  showing to clients does.
- Attachments in notes are copied (new files, not shared rows).
- Through an operation `copy_list(list, project, title, dates, actor)`
  recording one `created` event for the list (not one per to-do) and
  subscribing the copier to the list. API `POST /lists/{id}/copy/`,
  CLI `biwak list copy LIST --to PROJECT [--shift DAYS|--no-dates]`.

## Moving to another project

- **Top-level items** (decided 2026-11-22): lists, messages, folders,
  docs and files at the top of their project (anything inside a folder
  moves with its folder, or is moved out to the top first). "Move to…"
  already in the "More" menu gains other projects as targets (where the
  person may create such items); the API and CLI too. Single to-dos
  keep moving between lists of the same project only.
- **Everything comes along:** children, comments, reactions, events
  and history stay with the item (the old project's feed no longer
  shows them; the new one's does, including past events), checklist
  counts, public links (they keep working), bookmarks.
- **People not in the target:** assignees and subscribers who aren't
  members of the target project are listed in the modal before moving
  ("Cleo and Dan aren't in Website: they'll be unassigned and
  unsubscribed") and dropped; nobody is added to a project by moving.
- **Visibility** becomes the target's top level: the item keeps its
  switch, but if it would become visible to clients of the target
  (who aren't the source's clients), the modal asks first like
  "Show to clients…". Internal stays internal.
- **Mentions** of people not in the target stay as text, rendered as
  for non-members (`notifications.md`).
- **Records** a `moved` event in both projects' terms ("moved Launch
  checklist from Pitch to Website"); notifies nobody.
- Moving into or out of an archived project is refused.

## Done when

- Copying a list within a project and into another carries exactly the
  open work, keeps members' assignments, shifts or removes dates, and
  gets the target's visibility (asking before visible); API and CLI.
- Moving each top-level kind into another project keeps comments,
  history and children, drops non-members' assignments and
  subscriptions after listing them, asks before becoming visible to
  clients, and the feeds of both projects show the right events
  (tests through every entry point for visibility: views, feed, search,
  mails, mail replies, API).
- Help and the German catalog updated.
