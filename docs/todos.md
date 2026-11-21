# To-dos

A to-do is one thing to do. It belongs to a list, which belongs to a
project. Staff create lists with "New list" on the project's page.

## Lists and groups

- **Add a to-do** opens a form in the list: title, notes, assignees and
  a due date. <kbd>Ctrl</kbd>+<kbd>Enter</kbd> adds it and starts the
  next one, <kbd>Esc</kbd> closes the form.
- **Groups** are headings inside a list ("New group"). Rename or remove
  a group with the icons next to its name; removing it keeps its
  to-dos.
- **Order:** drag a to-do by its grip to move it within the list, into
  another group or into another list. Click several grips to select
  several to-dos and drag them together. Without a mouse, use "Move
  to..." in the to-do's "More" menu.
- **Board:** "Board" shows the groups as columns, "List" goes back. Your
  choice is remembered per list. Dragging between columns moves the
  to-do to that group.
- **Completed:** finished to-dos collapse into "Completed (N)" below
  the list; "Show more" loads older ones.
- Lists can be archived (in the list's edit page). An archived list
  stays readable.

## A to-do

Tick the checkbox on a row to complete it, or open the to-do and press
"Complete". "Reopen" undoes it. Everybody who sees a to-do can
complete it, and completing it completes it for all assignees. The
check pops, the title is struck through and the row fades away; the last
open to-do of a list gets a small burst and "All done." (not with reduced
motion set in your system).

"Edit" on the to-do's page changes everything:

- **Title and notes.** Notes are Markdown. A task list in them (lines
  starting with `- [ ]`) can be ticked in place, and the list's rows show
  how many are done.
- **Assignees:** any number. You can assign people who can see the
  to-do. Staff who aren't members of the project become members when
  you assign them. Clients can only assign members. While somebody is
  assigned they can't unsubscribe from the to-do ("Unassign me"
  instead).
- **Due on:** a date. Overdue to-dos are marked.
- **Repeat:** see below.

Below the notes are the comments, with reactions (a quick emoji or a
short text) and attachments ([Messages, docs and files](files.md)).
Type `@` to mention a person; they are told and subscribed
([Notifications](notifications.md)).

Between the comments, quiet lines say what happened to the to-do, oldest
first, with who did it and when (hover for the exact time): completed
and reopened, moved to another list or group, people assigned or
removed, a new title or due date, trashed and restored. One person's changes one after the other, within ten
minutes, are one line ("moved this to Done and completed it"); changes
that undo each other (completing and reopening, assigning and removing
the same person, a due date set and removed) leave nothing, and of a
title or due date changed several times the last one is shown. Clients see the lines of the
time the to-do was visible to them, and "another list" where a list's
name isn't theirs to know. Edits of the notes aren't listed; staff find
them in the History, linked below the timeline.

## Repeating

Choose how often it repeats: daily, weekly, monthly or yearly, with an
interval, weekdays, or the nth weekday of the month. Optionally set
"Repeats until" or "Repeats left".

Completing a repeating to-do creates the next one at the end of the
same list and group, with the same title, notes, assignees and
subscribers, due on the rule's next date after today (or after the due
date, when you complete it early). There is never a stack of open
copies. Comments and attachments stay with the completed to-do, and the
new one links back ("Previous: ..."). Reopening a completed to-do
doesn't remove the next one.

## The to-dos page

**To-dos** in the bar shows your open to-dos across all projects by
due date: Overdue, Today, This week (until Sunday), Next week, one
section per month after that, and No date. Every project has the same
page for its own to-dos. Completing works in place.

The filters apply as you change them:

- **project** and **assigned to**: across projects your own by default,
  or anybody, nobody active (nobody, or only people who are gone), or a
  person (clients: me, anybody, nobody active); a project's to-dos show
  anybody's by default;
- **assigned by**: "Me" shows the to-dos you gave to others;
- **state**: "Completed" shows finished to-dos, latest first, instead
  of the sections;
- **visibility** (staff): visible to clients or internal;
- **group by**: due date or project.

"Assigned to me" at the top (when someone else is chosen) shows your
to-dos again, with the other filters kept. Your browser remembers the
filters; "Reset filters" (there when a filter is set) forgets them. To-dos of archived
projects and archived lists don't show here.

## The calendar

"Calendar" in your menu shows a link to a calendar feed (iCal) of your
open to-dos that have a due date, as all-day events. Add it to your
calendar app as a subscription. The link needs no login, so keep it
to yourself; "Make a new link" replaces it and the old one stops
working. The feed only shows what you can see.
