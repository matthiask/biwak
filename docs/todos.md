# To-dos

A to-do is one thing to do. It belongs to a list, which belongs to a
project. Staff create lists with "New list" on the project's page.

## Lists and groups

- **Add a to-do** opens a form in the list: title, notes, assignees, a
  due date (and a start date once it's set) and how it repeats. <kbd>Ctrl</kbd>+<kbd>Enter</kbd> adds it
  and starts the next one, <kbd>Esc</kbd> closes the form.
- **Groups** are headings inside a list ("New group"). Rename or remove
  a group with the icons next to its name; removing it keeps its
  to-dos.
- **Order:** drag a to-do by its grip to move it within the list, into
  another group or into another list. Click several grips to select
  several to-dos and drag them together. Without a mouse, use "Move
  to..." in the to-do's "More" menu.
- **Board:** "Board" shows the groups as columns, "List" goes back, for
  this visit. How a list opens is its "Shown as" in "Edit" (list or
  board). Dragging between columns moves the to-do to that group.
- **Completed:** finished to-dos collapse into "Completed (N)" below
  the list; "Show more" loads older ones.
- **Archive:** finished lists go out of the way with "Archive" in the
  list's "More" menu or in the command palette; "Unarchive" brings them back. An archived list
  stays readable, but is left out of the project's lists (it is under
  "Archived lists"), of your to-dos, of the calendar link and of the
  palette's suggestions, and its recurring to-dos don't repeat. Nothing
  is archived automatically. To-dos are completed, not archived.

## Assigning several at once

On a list (also as a board) and on the to-dos page you can select
to-dos and assign them together, for example when somebody leaves and
their to-dos go to someone else:

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

`biwak todo assign 12 13 14 --to 7 [--replace]` does the same.

## A to-do

Tick the checkbox on a row to complete it (<kbd>Shift</kbd>+<kbd>x</kbd>
on the current row), or open the to-do and press "Complete". "Reopen" undoes it. Everybody who sees a to-do can
complete it, and completing it completes it for all assignees. The
check pops, the title is struck through and the row fades away; the last
open to-do of a list gets a small burst and "All done." (not with reduced
motion set in your system).

The to-do's page shows its facts (assigned to, due on, starts on, repeats) and
notes. Click them, the title or "Edit" (<kbd>e</kbd>) to change them in
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
- **Starts on:** for work that can't start yet, a start date shows once
  the due date is set; it can't be after the due date, and removing the
  due date removes it. Rows show both ("3–7 Dec"). Until it starts, the
  to-do stays out of your current work: My to-dos, the to-dos page and
  Home list it at the end under "Starting later (N)", closed until you
  open it. Lists, the board and search show it as always.
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

## Repeating

Choose how often it repeats: daily, weekly, monthly or yearly, with an
interval, weekdays, or the nth weekday of the month. Optionally set
"Repeats until" or "Repeats left".

Completing a repeating to-do creates the next one at the end of the
same list and group, with the same title, notes, assignees and
subscribers, due on the rule's next date after today (or after the due
date, when you complete it early). A start date keeps its distance:
starting four days before the due date, the next one does too. There is never a stack of open
copies. Comments and attachments stay with the completed to-do, and the
new one links back ("Previous: ..."). Reopening a completed to-do
doesn't remove the next one.

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
