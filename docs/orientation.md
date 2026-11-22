# Finding your way

The bar at the top has the same entries everywhere. On the right are
search, the lantern (your notifications) and your menu.

## Installing as an app

Chrome and Edge offer to install Biwak (the icon in the address bar);
on an iPhone or iPad use Share, then "Add to Home Screen". Biwak then
opens in its own window. It needs a connection like the website; it
doesn't work offline.

## Home

The brand ("Biwak") on the left leads to Home. It shows what needs you:

- your to-dos that are overdue or due in the next seven days;
- check-ins waiting for your answer;
- for staff, to-dos you assigned to others (waiting on others);
- recent updates in your bookmarked projects and wherever you were
  mentioned or assigned;
- your bookmarked projects and items;
- links to things you may need: search, the keyboard shortcuts, your
  calendar link, the notification settings and this help.

A section with nothing in it is left out. Rows with unread
notifications are marked; see [Notifications](notifications.md).

## Projects

A project is the place where the work on one thing happens: to-do
lists, messages, docs and files, check-ins, members.

- **Projects** in the bar lists the projects you can open as cards, with
  your open and overdue to-dos and the last activity. Bookmarked
  projects (the bookmark icon on a card) come first. "Activity" and
  "A–Z" switch the order; your choice is remembered.
- A project is open to all staff or limited to its members; clients
  only see projects they are members of, and in them only what is shown
  to them ([Clients](clients.md)).
- The project's page shows its to-do lists, the latest messages, docs
  and files, check-ins waiting for you, links and the latest activity.
  The "More" menu has the project's notification level, archiving and
  the trash; a list is archived from its own "More" menu.
- Staff add outside links (a design file, the live site) with "Add a
  link" on the project's page or in the command palette.
- **Members** lists who is in the project, by organization: your own
  first, then the clients' organizations, then partners'. Staff add
  people there, "Add people from …" an organization in the project, or
  invite them by email (see [People](#people)). "Add someone" and other long lists of choices
  (the person filter of the activity, a check-in's time zone) have a
  search field: type parts of the name, the organization or the address,
  in any order, then choose with the arrow keys and Enter or a click.
- Archived projects are out of the way; the projects page has an
  archive.

## To-dos

**To-dos** in the bar is your own list, by project (or by due date).
Every project and every list has its to-dos too. See [To-dos](todos.md).

## Activity

**Activity** is what happened, newest first, grouped by day, across
all your projects. Each project has its own, and "My activity" in your
menu shows what you did. Filters narrow it to a kind of item, a person
or an action (on a phone, behind "Filters"). Comments on the same item close together are shown as one
conversation.

## The lantern

The torch icon in the bar is your inbox: what you are told about, with a
dot while something is unread. Opening an entry reads it. See
[Notifications](notifications.md).

## Bookmarks

The bookmark icon on a project or an item keeps it on your **Bookmarks**
page (the projects first, then the items by project), on Home and in the
command palette. Bookmarks are yours; nobody else sees them.

## Search and the palette

The search field in the bar opens the command palette (<kbd>Ctrl</kbd>+<kbd>K</kbd>
or <kbd>/</kbd>): type to jump to a project, list, message, doc, file,
check-in or person, or to run an action of the page. "Search for ..." at
the end opens the search page, which finds words in titles and texts,
comments and answers. Filters: project, kind, only mine, and "Include
archived". You only find what you may see. See [Keyboard](keyboard.md).

## People

**People** lists everybody you may know, with their organization. A
person's page shows the projects you have in common and what they did.
Your own name is in Settings; "Edit the name…" on a person's page
corrects somebody else's (staff correct clients' names, admins
everybody's).
Clients only see members of their projects; partners see the people of
their projects, including staff who open them without being members.
Staff manage organizations from the People page: clients' organizations
and who belongs to them. Admins manage your own organization and
partners' (organizations with staff): who belongs to them, inviting
people into them, merging them and their email domains.

**Inviting people:** "Invite people" on the People page, or "Invite by
email" on a project's people page (with that project chosen), opens one
form for several people at once. Choose the projects, whether they are
notified by default or only when tagged, and fill a row per person:
address, name, organization (left empty: the one of the address's
domain) and, for admins, staff or client. "Add another" adds a row. New
people get one mail naming the projects; people who have an account are
added to them. If a row can't be invited (a deactivated person, staff
invited by somebody who isn't an admin), nobody is, and the form says
which row is wrong.

**Invitations:** until someone signs in for the first time, staff see
"Invited, not signed in yet" next to them, with who invited them and
when. "Resend" sends the invitation again, naming the projects they are
in now. "Withdraw…" removes them from all their projects and
deletes the account if nothing else refers to it (no comments, no
assignments); if something does, the account stays but is deactivated. Staff resend and withdraw clients' invitations,
admins everybody's. "Invited" on the People page lists
everybody who hasn't signed in yet, the oldest invitation first.

**Activating and deactivating:** people the import created can't sign in
and get no mail until someone activates them. "Inactive" on the People
page lists them; "Activate…" (there, or on the person's page) activates
them, with a checkbox to send the invitation mail (not to addresses that
bounced); nothing else changes. "Deactivate…" is for somebody who left:
they are signed out everywhere, their API tokens and calendar link are
deleted and they can't sign in, while what they did stays. They're taken
off their open to-dos (the to-dos' history says so). Staff change clients, admins also staff and
partners; you can't deactivate yourself or the last active admin.
`biwak people activate` and `deactivate` do the same for several people at
once, all or nothing.

## Your menu

Your name in the bar opens: My activity, Settings (your name, notifications, the
keyboard, appearance, profile image, sign-in: connected accounts,
passkeys, the authenticator app and sessions), Calendar,
Help and Sign out. Staff also find the link to the administration.

## Trash

Trashing an item (its "More" menu, then "Move to trash") moves it to the
project's trash, which you reach from the project's "More" menu. Trashed
items are deleted for good after 30 days, with everything in them;
until then "Restore" brings them back.
