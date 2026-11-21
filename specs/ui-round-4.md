# UI round 4: phones, and round 4 of the feedback

Feedback (2026-11-21): the to-do list on a phone is "funky": header
buttons of varying heights, and the checkbox and drag handle alone on
their line. Screenshots at 390 px wide of a list, a to-do and a project
page showed more of the same kind.

**Status:** open (spec, 2026-11-21).

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`. Every change gets a browser test at 390 px (`PhoneTest`)
and screenshots in the report.

**Depends on:** `ui-round-3.md` merged (it reuses the to-do row) and
`ui-round-2.md` part D (the projects page).

**Touches:**
- the page header include and its CSS (`.wb-page-header`,
  `.wb-page-actions`);
- the to-do row (`items/_todo.html`) and its CSS;
- the toolbar's CSS (`forms/_toolbar.html`);
- the visibility switch include;
- the comment form's label;
- `items/_todo_view.html`'s due badge;
- the feed's relative time.

## 1. Page headers

- **All buttons in a header have one height**, the `btn-sm` height,
  aligned in one row. Today List, Board and Edit stretch while History
  doesn't.
- **The List / Board switch** is a button group like elsewhere.
- **On phones the actions stay on one line:**
  - the less used ones move into "More" (History, To-dos by due date,
    Check-ins);
  - the rest show their icon only, with the label for screen readers
    and as `title`;
  - "More" never wraps alone onto a second line.
- **Which actions are "primary" per page** (shown on phones): the
  bookmark, Edit and the List / Board switch on lists; Complete, Edit
  and the bookmark on to-dos; the bookmark on projects. The rest goes
  into "More" on phones and stays visible on wide screens.

## 2. To-do rows

- **A grid:** handle | checkbox | content. The title wraps inside the
  content column, never under the checkbox.
- **The content column holds** the title, then a second line with
  assignees and the due badge.
- **The handle and checkbox stay at the top**, aligned with the title's
  first line.
- **The same row everywhere** it's used: lists, groups, "My to-dos",
  search results if they use it.

## 3. The editor toolbar

On narrow screens the toolbar wraps into a second row instead of running
past the edge. The buttons keep their size, and the paperclip is always
reachable.

## 4. Small things

- **The visibility switch's help text** ("Makes this list, 3 to-dos and
  0 comments visible to 1 client.") goes below the button as its own
  line on phones, not wrapped around it.
- **The comment form's field** has a proper label: "Comment", visually
  hidden, since the "Comments" heading is right above it. Not the
  lowercase "comment".
- **On a to-do's page** the overdue or "Today" badge sits next to the
  due date in the facts line, not on a line of its own above.
- **Relative times** say "just now" under a minute, never "0 minutes",
  in the feed and wherever `timesince` is shown.

## 5. Round 4 of `ui-feedback.md` (2026-11-21)

1. **"Sign out" in the "Me" menu**, as before part E, since it's
   understood to sign out here. The sessions card loses its help text
   about it and gets a "Sign out here" button instead (this browser's
   session, the same as the menu's).
2. **The to-do checkbox is aligned** with the title's first line on wide
   screens too, as section 2's grid does.
3. **"Add a to-do" and "New group" sit on one line** under a list, two
   quiet buttons side by side, wrapping only on phones if needed.
4. **"Show to clients" asks first.**
   - Making something visible to clients can reveal what shouldn't be
     revealed, so the switch opens a modal (`form_response`,
     `destructive=True` styling for the button): "Show this list to
     clients?". It says what becomes visible (the existing sentence:
     "Makes this list, 3 to-dos and 0 comments visible to 1 client.")
     and offers "Show to clients" and "Cancel".
   - Without JavaScript it's the form's page.
   - Hiding from clients ("Make internal") stays one click: it reveals
     nothing.
   - The same everywhere the switch is (lists, messages, folders, docs,
     files, check-ins), through the one include.
5. **The activity feed groups conversations, and nothing collapses.**
   - Comments on the same item, by anyone, each within an hour of the one
     before and on the same day, become one entry: "Conversation on
     Order the tent", with each comment below it, indented (who, the
     excerpt, the time).
   - Other events in between (a completion, a reaction) don't break it
     up: the conversation's comments gather at the newest one's place.
   - The existing merged entries ("Ada completed 5 to-dos in Launch") show
     their single items right away, indented, instead of inside a
     `<details>`. The feed has no `<details>` anymore.
   - Clients' feeds follow the same visibility rules per comment
     (`access.md`); a conversation shows only the comments they may see.
   - The API keeps its events as they are; the grouping is the page's.
   - `feed.md` gets the decision.
6. **"My to-dos" grouping as a filter:** it's a "Group by" field in the
   filter form, remembered like the other filters, not a field on
   `User`. The projects page's order is a small filter form the same
   way. Built separately (branch `view-prefs`), listed here for
   completeness.

## Done when

- Browser tests at 390 px:
  - header buttons have one height and fit one line on a list, a to-do
    and a project page;
  - a long to-do title doesn't move below the checkbox;
  - the toolbar doesn't overflow;
  - no horizontal scrolling on these pages.
- Django tests for "just now", the visibility modal (staff only, what
  it says, without JavaScript), the feed's conversations (staff and
  client) and the menu's label.
- Screenshots of the list, the to-do and the project page at 390 px and
  at 1200 px (nothing broke on wide screens), looked at before
  reporting.
