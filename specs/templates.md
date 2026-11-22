# Templates

Starting projects and lists from prepared ones. Decided with the user
2026-11-22, replacing "project templates are an agent skill": templates
are maintained by people in the app (one person or role keeps them
current) and used while projects run (an onboarding list, a list per
event), which a skill setting up projects doesn't cover.

**Status:** open.

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
  the feed across projects, the to-dos page, search unless asked) and
  also out of the calendar feed, mentions, notifications, the lantern,
  mails and digests: nothing that happens inside a template tells
  anybody. Its own feed and item history work as in any project.
- **The templates page** (`/projects/templates/`, linked from the
  projects page and the palette): cards like projects, with what each
  holds ("3 lists · 160 to-dos · 4 messages · 7 folders"), "New
  template", and per template "New project from this…".
- Archiving and trashing a template work as for projects.

## A new project from a template

- "New project from this…" (and "From a template" in the new project
  form): the new project form (name, description, all-access or
  limited, members, color) plus the template, prefilled from it.
- **Everything is copied**, top level as it is: lists (groups, open
  to-dos with notes and checklists, completed ones left out, through
  `copy_list()`), messages (title, text, category, pinned), folders
  with their docs and files (new files, not shared rows). Comments,
  reactions, history and events are not.
- **Assignees and dates** are copied as they are (real templates have
  none; a template that has them means them); assignees who aren't
  members of the new project are left out, not added.
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
- A to-do list library is simply a template project holding lists; no
  separate concept.

## Importing

The importer brings Basecamp's project templates and its to-do list
library over as templates (`import-basecamp.md`): the API serves both
like projects (decided 2026-11-22), once per import, so nobody
rebuilds them by hand.

## Not planned

- **"Save as template"** from a running project (decided 2026-11-22):
  templates are kept separately and change slowly.

## Done when

- Tests for the operations (copying everything, assignees left out,
  visibility, one event, nothing told), the pages as staff, a client
  and an external getting 404, templates left out everywhere listed
  above, the API and the CLI.
- The help's chapter on projects says how templates work.
