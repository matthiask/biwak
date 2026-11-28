# To-dos

A to-do is one thing to do. It belongs to a list, which belongs to a
project. Staff create lists with "New list" on the project's page.

## Lists and groups

- **Add a to-do** opens a form in the list: title, notes, assignees, a
  start and a due date and how it repeats. <kbd>Ctrl</kbd>+<kbd>Enter</kbd> adds it
  and starts the next one, <kbd>Esc</kbd> closes the form.
- **Add from text:** drop a Markdown or text file (`.md`, `.txt`)
  onto a list's page, or onto a list on the project's page, or use "Add
  from text…" in the list's "More" menu to paste a text or choose a
  file. Headings become groups (a heading with the name of an existing
  group adds to it), list items become to-dos (`- [x]` ones completed),
  and what's indented under an item becomes its notes, nested items as
  a checklist. A text without list items gives a to-do per line. The
  preview shows what will be added before you press "Add 12 to-dos";
  you can pick another list there. Up to 500 to-dos and 200 KB at once.
  Clients add new groups only in lists they created.
- **Groups** are cards inside a list, each with its name as the heading
  ("New group"); the to-dos outside groups come first, in a card of
  their own. The "…" next to a group's name edits it (its name and a
  color, which marks its card and heading), moves it up or down
  (without a mouse) or removes it; removing it keeps its to-dos. Drag a
  group by its grip to move it with its to-dos.
- **Order:** drag a to-do by its grip to move it within the list, into
  another group or into another list. Click several grips to select
  several to-dos and drag them together. Without a mouse, use "Move
  to..." in the to-do's "More" menu.
- **Board:** "Board" shows the groups as columns, "List" goes back, for
  this visit. How a list opens is its "Shown as" in "Edit" (list or
  board). Dragging between columns moves the to-do to that group and
  tells who is subscribed to it or watches the list (see
  [Notifications](notifications.md)). When the columns don't fit, the board takes the window's width and scrolls
  sideways.
- **Filters:** "Filters" in the list's header (it opens when you point
  at it) shows only the to-dos
  assigned to somebody with to-dos in the list, to you or to nobody, on the list and on the
  board, and in a list with groups only one group or the to-dos outside
  groups ("No group"); clicking a group's heading shows it alone, and
  "Add a to-do" there adds into it. A line below the header says what is
  set; "Reset filters" shows all again. Filtered by who is assigned, the
  groups stay; "Completed" counts only the matching ones. Dragging still works: a to-do lands next to the one you
  drop it beside.
- **Completed:** the latest finished to-dos show below the list, under
  "Completed (N)", newest first; "Show more" adds older ones.
- **Archive:** finished lists go out of the way with "Archive" in the
  list's "More" menu or in the command palette; "Unarchive" brings them back. An archived list
  stays readable, but is left out of the project's lists (under the
  lists, "3 archived lists" leads to them, at the end of the project's
  to-dos page), of your to-dos, of the calendar link and of the
  palette's suggestions, and its recurring to-dos don't repeat. Nothing
  is archived automatically. To-dos are completed, not archived.
- **Copy:** "Copy…" in the list's "More" menu (staff) copies its open
  work into this or another project: the description, the groups and
  the open to-dos with their notes, checklists, attachments and repeat
  rules. Not completed to-dos, comments or subscribers. Assignees stay:
  staff who aren't in that project are added to it; clients who won't
  see the copy are left out. Deactivated people stay assigned where they
  see the copy. The dialog names them first. The due dates stay, move by a number of days or go. The copy
  keeps the list's title, with "(copy)" if the project has a list of
  that name, and is internal unless you tick "Visible to clients"
  (which asks first).
- **Move to another project:** "Move to…" in the list's "More" menu
  moves it with everything in it: to-dos, comments, reactions, history
  and public links. Assignees stay: staff who aren't in that project are
  added to it; clients and subscribers who won't see it there are
  dropped. The dialog names them first, and asks first if clients there
  would see it. Its activity moves along to the new project; the old
  project's activity keeps one line, "moved Launch to Website". Single to-dos move
  between the lists of their project only.

## Changing several at once

On a list (also as a board) and on the to-dos page you can select
to-dos and assign, move or date them together, for example when
somebody leaves and their to-dos go to someone else:

- **Selecting:** <kbd>Ctrl</kbd>-click (<kbd>⌘</kbd>-click on a Mac) a
  to-do to add it to the selection or take it out, <kbd>Shift</kbd>-click
  to select everything from the one clicked last. With the keyboard,
  <kbd>x</kbd> selects the current row (<kbd>j</kbd>/<kbd>k</kbd> move),
  <kbd>Shift</kbd>+<kbd>↓</kbd>/<kbd>↑</kbd> selects on. A plain click
  opens the to-do as always. <kbd>Esc</kbd> or "Deselect" clears the
  selection.
- **Assign…** in the bar at the bottom opens a form: choose the people
  (only those who can be assigned to every selected to-do are offered)
  and whether they come "Instead of the current assignees"; without it
  they're added. Each new assignee gets one notification for all of
  them ("Ada assigned you 23 to-dos"). People taken out aren't told.
  If one of the to-dos was trashed or you can't see it anymore, nothing
  changes and the form says so. Taking somebody off is done per to-do.
- **Move…** moves them, completed ones too, to a list or one of its
  groups, to the top or the end, next to each other. Staff first choose
  the project, also another one, then the list, or "New list" (named
  after the list they come from, or "Moved to-dos"; rename it later),
  visible to clients when the lists they come from are. Before to-dos
  clients see go into an internal list, the form says clients won't
  see them any more. Into another project, the form first says who will be added to it
  and who won't see the to-dos there (they're unassigned and
  unsubscribed); their comments and history come along, and the
  project they left shows one line in its activity ("moved 23 to-dos to
  Plans in Website"). Clients move within the project, and only to-dos
  of one project. Moving to another list or project tells
  nobody.
- **Due date…** gives them all one due date ("Set a date"; start dates
  stay, so it can't be before one of them), moves their dates by a
  number of days ("Move by", start dates and "repeats until" too; to-dos
  without a due date stay as they are) or removes them ("Remove", the
  start dates too). Their subscribers are told once for all of them
  ("Ada changed the dates of 23 to-dos").

Every change is all or nothing: if one of the to-dos was trashed or you
can't see it anymore, nothing changes.

`biwak todos assign 12 13 14 --to 7 [--replace]`, `biwak todos move 12
13 --list 5 [--group 8] [--confirm]` (`--confirm` into another project,
once you've read who's added and dropped) and `biwak todos dates 12 13 --due 2026-12-20`
(or `--shift 7`, `--remove`) do the same.

## A to-do

Tick the checkbox on a row to complete it (<kbd>Shift</kbd>+<kbd>x</kbd>
on the current row), or open the to-do and press "Complete". "Reopen" undoes it. Everybody who sees a to-do can
complete it, and completing it completes it for all assignees. The
check pops, the title is struck through and the row fades away; the last
open to-do of a list gets a small burst and "All done." (not with reduced
motion set in your system).

A to-do that won't be done any more is **obsolete**: "Mark as obsolete"
in its "More" menu (or the command palette) completes it without it
counting as done. Whoever can complete a to-do can mark it obsolete;
"Reopen" undoes it. It shows among the completed ones, struck through
with "Obsolete", and its page says who marked it and when. A repeating
to-do marked obsolete creates no next one: the series ends.

The to-do's page shows its facts (assigned to, due on, starts on, repeats,
when and by whom it was created) and notes. Click them, the title or "Edit" (<kbd>e</kbd>) to change them in
place; "Save" or "Cancel" goes back. To choose people, type in the
field: the list shows who matches, <kbd>↑</kbd>/<kbd>↓</kbd> and
<kbd>Enter</kbd> pick, the × on a name removes it. From the keyboard,
<kbd>←</kbd> at the start of the field reaches the names:
<kbd>←</kbd>/<kbd>→</kbd>, <kbd>Home</kbd> and <kbd>End</kbd> move
between them, <kbd>Delete</kbd> or <kbd>Backspace</kbd> removes the one
you're on, and typing goes back to the field.

- **Title and notes.** Notes are Markdown. A task list in them (lines
  starting with `- [ ]`) can be ticked in place, and the list's rows show
  how many are done.
- **Assignees:** any number. You can assign people who can see the
  to-do. Staff who aren't members of the project become members when
  you assign them. Clients can only assign members. While somebody is
  assigned they can't unsubscribe from the to-do ("Unassign me"
  instead). Removing somebody from the project takes them off its open
  to-dos; the history shows it, nobody gets a notification. Completed
  to-dos keep them. Deactivated people stay assigned until someone hands
  their to-dos over; their mark is greyed and "(inactive)" follows their
  name. They aren't offered for new assignments.
- **Due on:** a date. Overdue to-dos are marked.
- **Starts on:** for work that can't start yet, a start date (the field
  before the due date); it needs a due date, can't be after it, and
  removing the due date removes it. Rows show both ("3–7 Dec"). Until it starts, the
  to-do stays out of your current work: My to-dos, the to-dos page and
  Home (also its "Waiting on others") list it at the end under
  "Starting later (N)", closed until you open it. Lists, the board and search show it as always.
- **Repeat:** see below.

Below the notes are the comments, with reactions (a quick emoji or a
short text) and attachments ([Messages, docs and files](files.md)).
Type `@` to mention a person; they are told and subscribed
([Notifications](notifications.md)).

Between the comments, quiet lines say what happened to the to-do, oldest
first, with who did it and when (hover for the exact time): completed
and reopened, moved to another list or group, people assigned or
removed, a new title or due date ("changed the dates" once there's a
start date), trashed and restored. One person's changes one after the other, within ten
minutes, are one line ("moved this to Done and completed it"); changes
that undo each other (completing and reopening, assigning and removing
the same person, a due date set and removed) leave nothing, and of a
title or due date changed several times the last one is shown. Clients see the lines of the
time the to-do was visible to them, and "another list" where a list's
name isn't theirs to know. Edits of the notes aren't listed; staff find
them in the History, in the to-do's "More" menu.

The line saying someone completed the to-do takes reactions of its own,
apart from the to-do's: a "🎉" for getting it done says something other
than a "👍" for the to-do. Only the person who completed it is told
("Reactions to you completing it"). If the to-do is reopened later, the
reactions stay on that line.

## Old to-dos

To-dos nobody touches don't stay forever. An open to-do is **stale**
when nothing happened on it for 90 days: no change, no comment, no
assigning, no move (reactions don't count). An overdue to-do counts from
its due date, one starting later isn't stale before its start.

The staff following a stale to-do get a mail ("12 to-dos will be marked
as obsolete"), at most one a day; clients don't. Two weeks later it's
marked obsolete by Biwak, unless somebody kept it: "Keep open" in the
mail or in the banner on the to-do's page, or any comment or change.
Who follows it hears about it being marked; "Reopen" brings it back.

A group can keep its to-dos for a year instead, for a backlog or a list
of ideas: "Keep untouched to-dos for a year" in the group's form (staff
only). Copies of the list and projects from a template keep it.

## Repeating

Choose how often it repeats: daily, weekly, monthly or yearly, with an
interval, weekdays, or the nth weekday of the month. Optionally set
"Repeats until" or "Repeats left". In lists and on the to-dos page, a
repeating to-do shows a repeat icon; pointing at it says how it repeats.

Completing a repeating to-do creates the next one at the end of the
same list and group, with the same title, notes, assignees and
subscribers, due on the rule's next date after today (or after the due
date, when you complete it early). A start date keeps its distance:
starting four days before the due date, the next one does too. There is never a stack of open
copies. Comments and attachments stay with the completed to-do, and the
new one links back ("Previous: ..."). The repeat moves to the new
to-do: the completed one doesn't repeat any more, so changing its date
changes nothing else. Reopening a completed to-do doesn't remove the
next one.

## The to-dos page

**To-dos** in the bar shows your open to-dos across all projects, by
project, list and group. Grouped by due date, they are in Overdue,
Today, This week (until Sunday), Next week, one section per month after
that, and No date. Every project has the same page for its own to-dos.
Completing works in place. Open to-dos whose start date hasn't come yet
are in "Starting later" at the end, the next to start first.

The filters apply as you change them:

- **project** and **assigned to**: across projects your own by default,
  or anybody, nobody active (nobody, or only people who are gone), or a
  person (clients: me, anybody, nobody active); a project's to-dos show
  anybody's by default. People who left are listed under "Inactive",
  so their open to-dos can be found and handed over;
- **assigned by**: "Me" shows the to-dos you gave to others, assigned
  to anybody else unless you choose who (with "Me" as the assignee,
  those you gave yourself); one you gave yourself and someone else
  counts too, though Home's "waiting on others" leaves out your own;
- **state**: "Completed" shows finished to-dos, latest first, instead
  of the sections;
- **visibility** (staff): visible to clients or internal;
- **group by**: project (the default) or due date.

"Assigned to me" at the top (when someone else is chosen) shows your
to-dos again, with the other filters kept. Your browser remembers the
filters; "Reset filters" (there when a filter is set) forgets them. To-dos of archived
projects and archived lists don't show here.

## The calendar

"Calendar" in your menu shows a link to a calendar feed (iCal) of your
open to-dos that have a due date, as all-day events (from the start
date to the due date, when there's a start date). Add it to your
calendar app as a subscription. The link needs no login, so keep it
to yourself; "Make a new link" replaces it and the old one stops
working. The feed only shows what you can see.
