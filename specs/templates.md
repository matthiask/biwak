# Templates

Starting projects and lists from prepared ones. Decided with the user
2026-11-22, replacing "project templates are an agent skill": templates
are maintained by people in the app (one person or role keeps them
current) and used while projects run (an onboarding list, a list per
event), which a skill setting up projects doesn't cover.

**Status:** built (2026-11-22), branch `templates`; the decisions
marked "proposed" below were made while building, for the user to
confirm.

## What real templates hold

From the Basecamp account being replaced (2026-11-22), as the measure
of what's needed:

- Project templates with one to four lists of 4 to 160 to-dos, mostly
  in groups (up to 15 per list); about a third of the to-dos have
  notes. **No assignees and no dates** on any of them.
- Next to the lists: a welcome message, a project brief and a few
  messages collecting questions for the client; an empty folder
  structure (5 to 9 folders); at most one doc.
- **No members**: the people come with the project, not the template.
- A library of five to-do list templates (10 to 90 to-dos), inserted
  into running projects; placeholders in titles ("Onboarding
  [name]").

## A template is a project

- `Project.is_template`, set when creating it ("New template" on the
  templates page) and never switched afterwards. A template is built
  and changed like any project: lists, groups, to-dos with notes and
  checklists, messages, folders, docs, files.
- **Who:** own staff see, use and change all templates (all-access,
  no members needed); clients and externals never see them (404). The
  audit log records changes.
- **Quiet:** templates are left out wherever archived projects are
  (`Project.objects.active()`, `archiving.md`: the projects page, Home,
  the feed across projects, the to-dos page, search: never, decided
  2026-11-22) and
  also out of the calendar feed, mentions, notifications, the lantern,
  mails and digests: nothing that happens inside a template tells
  anybody. Its own feed and item history work as in any project.
- **The templates page** (`/projects/templates/`, linked from the
  projects page and the palette): cards like projects, with what each
  holds ("3 lists · 160 to-dos · 1 check-in · 4 messages · 7 folders"), "New
  template", and per template "New project from this…".
- Archiving and trashing a template work as for projects.

## A new project from a template

- "New project from this…" (and "From a template" in the new project
  form): the new project form (name, description, all-access or
  limited, members, color) plus the template, prefilled from it.
- **Everything is copied**, top level as it is: lists (groups, open
  to-dos with notes and checklists, completed ones left out, through
  `copy_list()`), messages (title, text, category, pinned), folders
  with their docs and files (new files, not shared rows), check-in
  questions with their schedules (decided 2026-11-22: a weekly
  question belongs to a kind of project as much as its lists). Comments,
  reactions, history and events are not.
- **Check-ins** keep their schedule (paused ones stay paused; asked from
  the next date on) and the people asked, who are added as members when
  they wouldn't see the new project, like assignees below (proposed
  2026-11-22: a template has no members, but its questions can ask own
  staff; a question asking nobody asks nobody in the new project
  either). Questions in a template are never asked.
- **Assignees and dates** are copied as they are (real templates have
  none; a template that has them means them). **Assignments are kept**
  (decided 2026-11-22: unless there's a good reason not to): assignees
  who wouldn't see the new project are added as members, as "Copy…"
  does (`lists-across-projects.md`).
- **Client visibility** is copied (decided 2026-11-22): a template
  prepares what the client sees from day one, e.g. a welcome message.
  The new project form says what clients will see ("Visible to
  clients: Welcome, Questions for you").
- **One event** "created Website from the template Web project" in the
  new project; the copied items are created silently (like
  `copy_list()`'s to-dos), and the creator is subscribed to what they
  would be subscribed to as its creator. Changing the template later
  changes no project made from it.
- Through an operation `create_from_template(template, ..., actor)`;
  API `POST /api/v1/projects/` with `template`, CLI
  `biwak projects create --template ID`.

## A list from a template

- "New list" in a project also offers **"From a template…"**: the
  combobox of all lists in templates ("Onboarding [name] · Lists
  library"), then the copy modal of `lists-across-projects.md` (title,
  dates, visibility), the other way round. The title is asked there, so
  placeholders get filled in.
- **One to-do list library** (decided 2026-11-22): a template project
  named "To-do list library" holding lists; no separate concept.
- **No public links** in templates (decided 2026-11-22): "Share…" isn't
  offered on their items, and the API refuses them.

## Importing

The importer brings Basecamp's project templates and its to-do list
library (into the one "To-do list library") over as templates
(`import-basecamp.md`): the API serves both
like projects (decided 2026-11-22), once per import, so nobody
rebuilds them by hand.

## How it's built

- **Model:** `Project.is_template` (not editable), `is_quiet` (archived
  or a template). `ProjectQuerySet.active()` leaves out archived
  projects *and* templates, so everything listing running projects
  (the projects page, Home's cards, the to-dos page's projects,
  invitations, forwarding, suggested colors, joinable projects) leaves
  templates out; `templates()` lists them. `accessible_to()` gives
  templates to the own staff only, members or not.
- **Left out** next to `project__archived_at__isnull=True`:
  `project__is_template=False` in the feed across projects, the to-dos
  (`due.todos()`, so also Home and the calendar feed), Home's
  bookmarks, check-ins due (and `is_askable()`: questions in templates
  aren't asked), forwarding's lists, public links (they don't resolve),
  the all-projects page, the archived projects. Search: `templates`
  (the page's "Include templates", staff only; the API's `templates`;
  `biwak search --templates`), and searching inside a template finds
  its items. The palette lists templates after the projects, labelled
  "Template".
- **Quiet:** `notify()` tells nobody about events of templates (so no
  lantern, mails or digests), `mentions.update()` stores no mentions
  there, `notify_people()` subscribes nobody. Assigning inside a
  template adds nobody as member; `add_member()` refuses templates
  ("Templates have no members."), `update_project()` refuses making one
  limited; joining, "Add someone" and "Invite by email" are 404.
- **Operations:** `project_ops.create_template()`,
  `fill_from_template(project, template, actor)` (the one event:
  `created` without item, `template` and `template_id` in its data;
  the feed names the template only to readers who can open it,
  `feed.add_projects()`; the API drops it otherwise) and
  `create_from_template(template, actor, members, **fields)`.
  `items.operations.copy_template()` copies with `copy_list(...,
  quiet=True)` (the title as it is, no event, the actor subscribed;
  assignees who wouldn't see the copy added as members, recording
  "added"), check-in questions (`checkins.operations.copy_question()`:
  the schedule, paused or not, and the people asked, added as members
  the same way; the creator and the people asked subscribed, no event),
  messages, folders with docs and files (the newest
  version, as a new file), attachments in texts as new files; the
  project's orders of files and messages too.
- **Pages** (`biwak/projects/template_views.py`): `/projects/templates/`
  (`?archived=1`), "New template" (`template_create`), the new project
  form's "From a template" select and `?template=ID` ("New project
  from this…" on the cards and the template's page, prefilled with the
  description and the color, the banner "Visible to clients: …"),
  `list_from_template` (two steps: the combobox, then the copy form).
  The template's page says it's a template, has no "Members", "Join"
  or "Notifications". Palette: "Go to templates", "New template",
  "New project from this…", "New list from a template…".
- **API/CLI:** `ProjectOut.is_template`; `GET projects/?templates=true`
  (`biwak projects --templates`); `POST projects/` with `template`,
  `member_ids` (added before copying) or `is_template` (`biwak project
  add NAME --template ID --member PERSON`, `--as-template`); a list
  from a template is `POST lists/{id}/copy/` (`biwak list copy`).
- **Importer:** `import_basecamp --templates` (`import-basecamp.md`).

## Decisions made while building (confirmed by the user 2026-11-22)

- **Not copied:** archived lists, trashed items, drafts, completed
  to-dos (as `copy_list()`) and the project's links; pinned messages
  stay pinned.
- **The new project form** is prefilled with the template's description
  and color, not its name. The clients' banner shows when the template
  is known (from "New project from this…", or the organizations step);
  choosing a template in the select of a form without organizations
  doesn't ask first (no clients yet).
- **Copying lists into templates** ("Copy…") is allowed, templates
  listed after the projects; moving into or out of a template is
  refused ("Nothing moves into or out of a template."), and templates'
  items offer no other projects to move to.
- **Archived templates** have their own archive on the templates page,
  not on the projects page's archive. Projects have no trash, so
  neither do templates.
- **A project's own events** don't merge with its items' in the
  activity ("created Website from the template …" stays apart from
  "created Launch").

## To change (decided 2026-11-22, not built yet)

- Search never finds templates: drop "Include templates", the API's
  `templates`, `biwak search --templates` and searching inside a
  template.
- One "To-do list library" for the importer, whatever the bucket's
  name.
- No "Share…" in templates, the API refusing public links there.

## Not planned

- **"Save as template"** from a running project (decided 2026-11-22):
  templates are kept separately and change slowly.

## Done when

- Tests for the operations (copying everything, assignees left out,
  visibility, one event, nothing told), the pages as staff, a client
  and an external getting 404, templates left out everywhere listed
  above, the API and the CLI. (`biwak/projects/test_templates*.py`,
  `biwak/test_cli_templates.py`, `biwak/importer/test_templates.py`)
- The help's chapter on projects says how templates work
  (`docs/orientation.md`, "Templates").
