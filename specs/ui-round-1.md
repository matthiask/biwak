# Quieter pages: modals, view mode, pickers

From the user's first round of feedback after testing
(`specs/ui-feedback.md`, 2026-11-21): pages show too many forms at once,
the to-do page is an edit form rather than a page to read, and some
controls don't scale.

**Status:** parts 1 and 2 built (modals, the quieter pages: New list, New
group and renaming, notification level, Move to and Trash in the "More"
menu, adding and inviting members, editing and creating a project, the
palette's "New project"), the navigation's search field opens the palette
(`keyboard.md`). Wording chosen: trash modal "Move to the trash?" / "It
can be restored for 30 days."; notifications "Your own level for this one
instead of the one of the project. The activity feed always shows
everything." Parts 3 and 4 built (branch `ui-todo-view`, "Built: view mode
and the picker" below). Parts 5 and 6 open.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. Split into the parts below, in this order, since later
parts use the modals: (1) modals, (2) quieter pages, (3) the to-do in
view mode, (4) the assignee picker, (5) overdue, (6) the projects page.

**Depends on:** the editor (`editor.md`, built), ticking while editing
(built). The live editor and the lantern (`collaboration.md`,
`lantern.md`) are being merged; the parts touch the same templates, so
start after that merge.

## 1. Modals

Copy Governance's modal (`~/projects/sites/governance/frontend/modal.js`
and `governance/modals.py`; keep the copyright line, `NOTICE`):

- Links with `data-modal` load their form into a `<dialog>` with the
  `HX-Modal` header; the form posts there; on success the view answers
  `HX-Redirect` (or a refresh of the page), on errors it renders the form
  again in the dialog.
- Without JavaScript, or with a modifier key, the link opens the form's
  own page, so every modal form is also a page.
- Escape closes an unchanged form; a changed one needs Escape twice
  (Governance's rule). Focus returns to the link.
- One template for modal forms (`modal_form.html`) with a title, the
  client banner where the item is visible to clients, and the buttons.

## 2. Quieter pages

Each of these becomes a button or a "More" menu entry opening a modal:

- **New list** on the project page: a button like "New message".
- **New group** on a list: a button; renaming a group too.
- **The notification level** at the bottom of a list (and of other
  items): "Notifications…" in the "More" menu, a modal titled
  "Notifications for this list" that says what it does.
- **Move to…** and **Trash** on a to-do (and other items): entries in the
  "More" menu; moving opens a modal with the list and group choice;
  trashing asks in a modal ("Move to the trash? It can be restored for
  30 days.").
- Adding and inviting members, editing a project and the palette's
  "new …" actions use the same modals where a form exists.

## 3. The to-do in view mode

Like Basecamp: a to-do's page shows the to-do, not an edit form.

- **Reading:** the title as the heading, the rendered notes (checklists
  tickable), assignees, the due date and the repeat rule as text (`describe()`),
  attachments, then the comments. The reactions block sits right under
  the to-do. Nothing repeats the title.
- **Editing:** clicking the title, the notes or a field (or "Edit" in the
  "More" menu, or `e`) swaps the view for the edit form in place
  (htmx), focused on what was clicked; Save and Cancel (or Escape) swap
  back. Without JavaScript, "Edit" opens the form as its own page.
- **The editing marker** (`editor.md`) is set only while the form is
  shown, so ticking is blocked only while someone really edits.
- **The same click to edit** (decided 2026-11-21) for messages, files and
  check-in answers: their pages show them, clicking the title or text
  switches to the edit form in place. Docs keep the live editor.
- **Repeat** (decided 2026-11-21): the end fields ("until", "repeats
  left") move into the rule widget's fieldset and show only when a
  repeat is chosen, everywhere.

## 4. The assignee picker

For projects with dozens of people:

- Assignees as pills, each with × to remove; an "Assign…" field opening
  a list on click and filtering while typing (people who can be assigned,
  members first, `assignable_people()`), keyboard navigation like the
  `@` list (`mentions.js` can be the base).
- Used in the inline form, the to-do's edit form and the board.
- Without JavaScript the underlying `<select multiple>` stays usable.
- Clients see only members (the existing rule).

### Built: view mode and the picker (2026-11-21)

- **No special views:** the edit form is the item's edit page rendered
  with the form in the `#live-text` region (the to-do's page itself at
  `/todos/<id>/edit/`, `todo_edit`; for messages, files and answers the
  existing edit pages, whose form sits in a region of the same id). htmx
  fetches that page and takes the region out of it (`hx-select`); the form
  posts with htmx, the view redirects as before and htmx takes the
  region and, for to-dos, messages and files, the header (`hx-select-oob`)
  out of the page it lands on; Cancel fetches the item's page and takes the
  region. Without JavaScript (or fetched as a page of its own) the form is
  a plain form, the Cancel a plain link: the templates add the `hx-*`
  attributes only for requests with `HX-Request` (`htmx` in the context,
  `biwak/modals.py`).
- **Click to edit** (`frontend/view-edit.js`): elements with
  `data-edit-focus` (the title, the text, the facts of a to-do) inside an
  element with `data-edit-url` (and `data-edit-region`, default
  `live-text`); not for clicks on links, buttons or boxes in the text, not
  when text is selected. The "Edit" link (`data-edit-open`, the palette's
  "Edit" and `e` click it) does the same, focused on the title. While the
  form is shown the heading and "Edit" hide (`data-hide-title`). Escape
  cancels an unchanged form; a changed one needs it twice within 1.5
  seconds (like the modals).
- **The to-do's view:** assignees, due date and repeat rule as three facts
  ("Nobody", "No date", "Doesn't repeat" when empty), the notes ("Add
  notes…" when empty); the repeat rule with its end and count. Reactions
  sit under the text. The region `live-form` is gone; `live-text` holds the
  view or the form. Answers: the author's own answer is clickable
  (`answer-<id>-text`).
- **The marker** is set when the form is rendered and renewed every minute
  while it's connected (`editing.js` watches forms htmx inserts), released
  by Cancel, saving and leaving the page; the view sets none, so ticking
  works there. A region showing a form isn't replaced by live updates
  (`[data-view-form]`, as a focused field); what waited is dropped when the
  region was swapped by htmx meanwhile.
- **The end fields:** `recurrence_ends_on` and `recurrence_count` stay form
  fields with the same names (`EndsOnInput`, `EndsCountInput`) but render
  inside the rule widget's fieldset (`RepeatForm.ends()`), hidden by
  `rule-widget.js` without a repeat (shown for a rule set elsewhere). The
  inline form's own copy and `data-repeat-ends` are gone.
- **The picker** (`frontend/assignees.js`): the form field is an
  `AssigneeField` with a `<select multiple data-assignee-picker>` (options
  with `data-member`); JavaScript hides it and shows pills with ×, a field
  opening the list on focus and click, filtering while typing, Up/Down,
  Enter, Escape, Backspace removes the last pill. Non-members say "not in
  the project yet". The inline form uses the same select. The board has no
  assignee editing, so nothing there.
- **Tests:** `biwak/items/test_view_mode.py`; Playwright in
  `biwak/test_e2e_view_mode.py`.
- **Open questions:** see the report of the branch (Escape on a changed
  form, empty facts' wording, the board).

## 5. Overdue

- An open to-do whose due date is before today (`schedules.today()`)
  shows its date as a small danger-toned badge ("Overdue · 18. Nov"),
  on lists, the board, "my to-dos", the list by due date, the to-do's
  page and the palette's results; due today gets a quieter "Today"
  badge (decided 2026-11-21). Completed to-dos are never overdue.
- A danger tone in the palette tokens (`--wb-tone-danger`), checked for
  contrast with the others.

## 6. The projects page

- Archiving and unarchiving a project, and switching between active and
  archived projects, with htmx: the card moves out or the list swaps,
  without a reload; a short "Archived. Undo" message (the user likes the
  current archive, `specs/ui-feedback.md`).

## Done when

Each part with Django tests for the views (also as a modal: the
`HX-Modal` request, errors in the dialog, the redirect) and Playwright
tests for the interaction; everything also working without JavaScript;
clients seeing only what they may (no member lists beyond members in
the picker, no staff-only menu entries).
