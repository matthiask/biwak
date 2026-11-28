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

- your to-dos that are overdue or due in the next seven days (those
  that haven't started yet under "Starting later");
- check-ins waiting for your answer;
- for staff, to-dos you assigned to others (waiting on others; those
  that haven't started yet under "Starting later");
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
  your open and overdue to-dos and the last activity; click anywhere on
  a card to open the project. Bookmarked
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
  first, then the clients' organizations, then externals'. The project's
  page shows each organization once with a row of its people's pictures
  (the name shows on hovering, a click opens their page); "Manage" (or
  "All") lists them with their names. Staff add
  people there, "Add people from …" an organization in the project, or
  invite them by email (see [People](#people)), and remove them with
  "Remove" in their row, which asks first.
  Clients and externals can't remove anybody, themselves included: to
  hear less about a project, change its notifications instead (see
  [Notifications](notifications.md)). "Add someone" and other long lists of choices
  (the person filter of the activity) have a
  search field: type parts of the name, the organization or the address,
  in any order, then choose with the arrow keys and Enter or a click.
- Archived projects are out of the way; the projects page has an
  archive.

## Templates

New projects can start from a template, a project kept for that
(staff only; clients and externals never see templates).

- **Templates** on the projects page (and "Go to templates" in the
  command palette) lists them as cards with what each holds. "New
  template" adds one; you build and change it like any project: lists
  with groups and to-dos, check-ins, messages, folders, docs and files.
  Templates have no members, all staff see them, and their check-ins
  are never asked.
- **Nothing in a template tells anybody:** no notifications, no mails,
  no mentions. Templates stay out of the projects page, Home, the
  activity across projects, your to-dos, the calendar link and search.
- **"New project from this…"** on a template's card or page (or "From
  a template" in the new project form) creates a project with a copy of
  everything at its top level: the lists with their groups and open
  to-dos (with notes and checklists), the check-ins with their
  schedules and the people asked, the messages (pinned ones stay
  pinned), the folders with their docs and files. Not comments or
  history. What's visible to clients in the template is visible in the
  new project; the form says which. Assignees and the people asked
  are kept: those who wouldn't see the new project become its members. Changing the
  template later changes no project made from it.
- **A list from a template:** "New list" offers "From a template…":
  pick a list of any template, then give it a title (fill in what the
  template leaves open, like a name) and choose what happens to its due
  dates, as when copying a list (see [To-dos](todos.md)). A template
  holding only lists is a library of lists.
- Templates are archived like projects.
- **All projects** (admins, linked below the cards, in your menu and in
  the command palette) lists every project in a table: whether it's
  limited or archived, how many active staff members it has, its
  clients' organizations, its open to-dos and how many of them only
  inactive people are assigned to, and the last activity. Filters show
  projects without an active staff member, limited ones, those with
  to-dos of inactive people, and archived ones too. For projects you
  can't open it shows counts only; "Join" gets you into a limited one
  (the project records it). `biwak projects --all` does the same.

## To-dos

**To-dos** in the bar is your own list, by project (or by due date).
Every project and every list has its to-dos too. See [To-dos](todos.md).

## Activity

**Activity** is what happened, newest first, grouped by day, across
all your projects. Each project has its own, and "My activity" in your
menu shows what you did (the activity filtered by you). Filters narrow it to a kind of item, a person
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
comments and answers. Filters: project, kind, "Only mine" and "Include
archived". You only find what you may see. See [Keyboard](keyboard.md).

## Writing texts

Every text field (notes, comments, messages, docs, file descriptions,
answers) shows the text as it will look: bold is bold, a list is a
list. The toolbar above it has bold, italic, link, heading, lists,
checklist, quote, code, mention and "Attach files"; the buttons light
up for what's under the cursor, and pressing one again takes it off.

- <kbd>Enter</kbd> starts a new paragraph (in a list, a new item),
  <kbd>Shift</kbd>+<kbd>Enter</kbd> a new line in the same one, and
  <kbd>Ctrl</kbd>+<kbd>Enter</kbd> sends the form.
- Typing Markdown works too: `**bold**`, `*italic*`, `` `code` ``,
  `~~struck~~`, `# ` for a heading, `- ` or `1. ` for a list, `[ ] ` for
  a checkbox, `> ` for a quote, three backticks for code, `---` for a
  line. <kbd>Backspace</kbd> right after turns it back into what you
  typed. Addresses like `www.example.org` become links.
- Keys: <kbd>Ctrl</kbd>+<kbd>B</kbd>, <kbd>Ctrl</kbd>+<kbd>I</kbd>,
  <kbd>Ctrl</kbd>+<kbd>K</kbd> (a link: type its address, Enter),
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>7</kbd>/<kbd>8</kbd>/<kbd>9</kbd>
  (numbered list, bulleted list, checklist), <kbd>Tab</kbd> and
  <kbd>Shift</kbd>+<kbd>Tab</kbd> move list items in and out.
- Click a checkbox in the text to tick it.
- Type `@` to mention somebody (staff can mention a team).
- **Tables:** "Insert table" in the toolbar. While you're in a table a
  small bar above it adds rows and columns, deletes them or the table,
  and aligns the column left, center or right. <kbd>Alt</kbd>+<kbd>F10</kbd>
  in the table goes to it, <kbd>Esc</kbd> back to the table.
- Paste from web pages, mails, Word or Google Docs and the formatting
  stays. Pasted plain text that is clearly Markdown (headings, lists,
  tables, code blocks, links) is formatted too, and
  <kbd>Ctrl</kbd>+<kbd>Z</kbd> right after turns it back into the text;
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> pastes plain
  text. Pasted or dropped files are attached.
- **Markdown** (the last button) shows the text's source, Markdown, for
  what the editor doesn't show, such as pasting a piece of Markdown;
  click it again to go back. Texts are stored as Markdown, and a text
  you didn't change is saved exactly as it was.

## People

**People** lists everybody you may know, with their organization. A
person's page shows the projects you have in common and the last
things they did that you can see, with "All activity" for the rest.
Names in the activity, a to-do's timeline and elsewhere open the
person's page.
Your own name is in Settings; "Edit the name…" on a person's page
corrects somebody else's (staff correct clients' names, admins
everybody's).
Clients only see members of their projects; externals see the people of
their projects, including staff who open them without being members.
Staff manage organizations from the People page: clients' organizations
and who belongs to them. Admins manage your own organization and
externals' (organizations with staff): who belongs to them, inviting
people into them, merging them and their email domains.
An organization's email domains suggest it when somebody with such an
address is invited. When an organization gets a new domain, the form
asks once before saving whether the people without an organization who
have an address there move into it too, all ticked (inactive people and
people who left included); people you may not move (staff, unless
you're an admin) are left out.

**Marks:** everybody has a mark next to their name: their photo, or a
small drawing (an ibex, a tent, a fox, …) in white on their color.
Everybody gets a drawing when their account is created, one few people
of their organization have. Choose yours in Settings, "Profile image":
under **Drawn**, a click on a drawing saves it; under **Photo**, upload
a JPEG, PNG or WebP image instead. The photo is shown while you have
one, "Remove" brings the drawing back. The color comes with your
account and can't be chosen.

**Away:** somebody out of office has a small moon on their mark;
hovering over it says until when, with their note ("Away until 3 Dec:
back on the 4th"). Their page says so too, and picking them as an
assignee, typing `@` or looking at a team says "away until 3 Dec".
Assigning or mentioning them shows their note once below the field,
and an open to-do's page shows it under "Assigned to", its row "(away
until 3 Dec)" after their name, also in the due-date lists; they can still be assigned and mentioned. Clients see it for the people
they may know. Setting yourself away: [Notifications](notifications.md).

**Inviting people:** "Invite people" on the People page, or "Invite by
email" on a project's people page (with that project chosen), opens one
form for several people at once. Choose the projects, whether they are
notified "Only when tagged" (the default) or about "Everything new", and fill a row per person:
address, name, organization (left empty: the one of the address's
domain) and, for admins, staff or client. Leaving the address fills in
the organization of its domain and, for admins, staff for your own and
external organizations, client otherwise, unless you changed those
fields in that row. "Add another" adds a row. New
people get one mail naming the projects; people who have an account are
added to them. People the import created who are waiting to be
activated are activated and get the invitation, naming all their
projects. If a row can't be invited (somebody who left, who needs
activating first, staff invited by somebody who isn't an admin), nobody
is, and the form says which row is wrong.

**Invitations:** until someone signs in for the first time, staff see
"Invited, not signed in yet" next to them, with who invited them and
when. "Resend" sends the invitation again, naming the projects they are
in now. "Withdraw…" removes them from all their projects and their open
to-dos and deletes the account if nothing else refers to it (no
comments, no completed to-dos); if something does, the account stays but is deactivated. Staff resend and withdraw clients' invitations,
admins everybody's. "Invited" on the People page lists
everybody who hasn't signed in yet, the oldest invitation first.

**Activating and deactivating:** people the import created can't sign in
and get no mail until someone activates them. "Inactive" on the People
page lists them; "Activate…" (there, or on the person's page) activates
them, with a checkbox to send the invitation mail (not to addresses that
bounced, and not to somebody in no project: add them to one first);
nothing else changes. "Deactivate…" is for somebody who left:
they are signed out everywhere, their API tokens, calendar link and
devices for push notifications are deleted and they can't sign in, while what they did stays. They stay
assigned to their to-dos, marked as inactive, until someone hands them
over; mentions of them show their name, marked as inactive too, but they
can't be mentioned anew. The question before deactivating says how many open to-dos they
have (the link lists them on the to-dos page, where "Assign…" hands
them over) and which projects they're the only active staff member of,
counting only projects you can open; it never stops you. Staff change clients, admins also staff and
externals; you can't deactivate yourself or the last active admin.
`biwak people activate` and `deactivate` do the same for several people at
once, all or nothing.

The People page shows the active people ("Active"); staff find the
others under "Inactive" and "People who left". Every list is grouped by
organization.

**People who left** (deactivated, or no longer in Basecamp when
imported) don't show under "Active"; the filter "People who left"
lists them with the day they left, as does their page. "Inactive" lists
only people waiting to be activated; somebody who left is activated
again from their page.

**Teams:** a team is a named set of people ("Design team") for picking
several at once. Staff find teams among the people wherever they pick
several: assignees, subscribers, whom to tell, the people a check-in
asks, and the list that opens
when typing `@`. Picking a team picks its members at once, as if you had
picked each of them: a pill per member, a mention per member. Only the
members who can be there are added: active, able to see the item and in
the project (a team never adds anyone to a project), and not those
picked or mentioned already; the entry says beforehand how many are
left out and why ("3 of 5: 2 can't see internal items"). Only the people
are kept: changing or deleting the team later doesn't change who was
assigned, subscribed or mentioned with it. Your own staff create, change
and delete teams under "Teams" on the People page; members can be
anyone, staff, externals and clients. Clients never see teams. Teams are
a shortcut of the pages: through the CLI, the API and replies by mail
a team's name isn't expanded.

**The whole project at once:** when adding subscribers ("Subscribers…")
or when posting ("Subscribers"), staff find two entries at the top of
the list: **Staff on this project** (your staff and the externals) and,
when clients can see the item, **Everybody on this project** (the
clients too). Picking one adds a pill for each active member not
subscribed already, and says how many; take out whoever shouldn't be
there before saving.

## Your menu

Your name in the bar opens: My activity, Settings (your name, the
language, notifications, the keyboard, appearance, profile image,
sign-in: connected accounts, passkeys, the authenticator app and
sessions; what you change there is saved as you go: a choice at once, a
text when you leave the field), Calendar,
Help and Sign out. Staff also find Public links there; administrators
All projects, after My activity, and the link to the administration.

## Language

Biwak speaks English and German. Settings, "Language": Automatic
follows your browser's language, or choose Deutsch or English; the page
reloads in it. Mails follow your choice too; with Automatic they're in
English, or in the language you were invited in. `biwak settings
--language de` (or `en`, `auto`) does the same from the command line.
This help is in English and German; a page not translated yet is in
English.

## Trash

Trashing an item (its "More" menu, then "Move to trash") moves it to the
project's trash, which you reach from the project's "More" menu. Trashed
items are deleted for good after 30 days, with everything in them;
until then "Restore" brings them back.
