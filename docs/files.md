# Messages, docs and files

## Messages

The **message board** of a project (Messages on the project's page) is
for announcements and discussions that aren't about one to-do. Pinned
messages on top, then the rest, each with its category, author, date and
number of comments.

- **Order:** "Latest update" (the default: a new comment brings a
  message up and its row says who commented last and when, editing
  doesn't count) or "Newest posts", chosen by staff on the board for
  everybody and followed by the project page.
- **New message:** title, text (Markdown), an optional category,
  "Visible to clients" (staff), and "Subscribers": they hear about it
  and its comments. You and whoever wants to hear about something new
  ("Everything", or subscribed to the folder;
  [Notifications](notifications.md)) are in it already, with a lock
  instead of ×: you can't take them out (point at one to see why). Add
  others by typing a name, for example people who hear only when
  tagged. Ticking "Visible to clients" adds the clients who want to hear
  and lets you add clients of the project; an internal message tells no
  client.
- Staff **pin** a message (its page or the row's menu) to keep it on
  top for everybody. The categories are set up by an administrator.
- Messages have comments and reactions like to-dos. Clients can post
  messages where they can see the board.

## Docs and files

**Docs and files** on the project's page opens the project's root
folder. Its contents show as tiles: folders first, then docs and files,
in the folder's order; images show a preview, files their size, docs with a task list
how many are done, folders what they hold directly ("2 folders · 3 files"). Inside a folder the first tile, "..", leads to the
folder above (or the project's top level); the path above the title
does too. Staff create what is here: "New folder", "New doc", "Upload
files". A folder's "More" menu has "Edit…" (its title and color); move things between
folders with "Move to…" in their "More" menu. What's at the top of the
project (folders, docs and files) moves to another project there too,
with everything in it; something inside a folder moves with its
folder, or to the top first. Messages have "Move to…" for other
projects as well. Assigned staff who aren't in the other project are
added to it, clients and subscribers who won't see it there are
dropped (the dialog names them first), and if clients there would see
it, it asks first. Every tile has the same
menu behind its "…" button in the top-right corner (it shows when you
point at the tile or reach it with Tab), so you can edit a folder, move
something or move it to the trash without opening it. Staff also show
top-level folders, docs and files to clients there ("Show to
clients…"), or hide them again ("Hide from clients").

**Folder colors:** a folder can have a color, chosen as a row of swatches
in "New folder" and "Edit…" (staff; "None" is the default). Its tile and
the icon in its page's title take the color, so you find it at a glance;
folders without a color are grey.
Clients see the colors too.

**Moving:** drag a tile onto a folder, onto "..", or onto a folder in
the path above the title. **Several at once:** Ctrl-click (Cmd-click on
a Mac) adds a tile to the selection or takes it out, Shift-click selects
all tiles from the last one clicked; with the keyboard, <kbd>x</kbd>
selects the current tile or takes it out and Shift with the arrow keys selects on to the
next one. A plain click opens the tile as always. With a selection a bar
shows "Move to…", "Move to trash" and "Deselect" (or press Escape);
dragging one of the selected tiles moves them all. You move what you may
change; clients only what they added.

Staff choose the order of a folder's contents with "Order…" in its
"More" menu (for the top level in the "More" menu of "Docs and files"):
alphabetical (the default), reverse alphabetical, newest first or oldest
first, by when they were created. Folders always come first, in the
same order. Everybody sees the order chosen.

### Docs

A doc is a page of Markdown text, such as a brief or a set of notes.
Its title is the first line of the text: a heading such as `# Brief`, or
else the line itself, shown as the page's heading. Change the first
line to rename the doc; lists, search and the activity feed follow. An
empty doc is "Untitled".

**New doc** opens the editor at once, the cursor in the first line,
which says "Title" until you type: type the title first, then the text.
Any doc whose first line is empty says so there. The first line is the
doc's title: the toolbar's heading makes it a big heading there, and a
smaller one on every other line. Until you
write something it's only yours: nobody else sees it, it isn't in the
folder, the activity or search, and an empty one is deleted after a day.
With the first text it's a doc (the browser's address becomes the doc's)
and it's in the folder, telling nobody yet. When you click "Done" the
first time, you're asked "Tell people about it?": those who want to
hear about something new are told either way (the pills with a lock
under "Subscribers"); add others there (and a note) and "Tell them
too", or "No one else" to add nobody. A new doc at the top level is
internal: to tell clients, show it to them afterwards ("Show to
clients…" in "More" on its page) and add them with "Subscribers…" and
"Tell them now".
If you never click "Done", those who want to hear are told an hour after
your last change (restoring the doc from the trash, also with its
folder, starts the hour again). You're asked only once; later, add
people with "Manage…" next to the subscribers.

- **Edit** opens the doc for editing together: everybody who edits it
  sees the others' changes as they are typed, and changes are saved as
  you type. You see who else is there. The editor has the same toolbar
  and keys as every text field (bold, italic, links, headings, lists).
  Someone who can see the doc but not change it can "Watch live".
- **Versions** (staff): saving creates a version when the last one is
  older than ten minutes or by somebody else, and "Save as a version"
  makes one on request. Open an older version and "Restore this
  version" saves its text as a new version.
- Staff can make a doc read-only ("Make read-only"); nobody can edit
  it until it's made editable again.

### Files

**Uploading:** "Upload files" opens a list for the files you choose, or
drop files from your computer anywhere onto a folder's page (onto a
folder's tile, "..", or a folder in the path above for that folder).
Each file shows its name, which you can change (the extension stays),
and its size; remove one with ×, or drop more. Below, once for all of
them: "Visible to clients" (at the top level; in a folder they follow
the folder) and "Subscribers", as for a new message. "Upload" sends them one after another;
a file that can't be uploaded (too big) says so on its row while the
others go on. The people notified get one notification and one mail for
all of them ("Ada uploaded 5 files to Minutes"), not one per file; more
files uploaded into the same folder within ten minutes join it, and the
mail waits until all files are up, or an hour at most.

A file's page shows a preview for images and PDFs, its description,
comments and "Download". "Replace" (or "Upload a new version") puts a
new version in place: the link, the comments and the earlier versions
stay. Earlier versions are for staff. Clients can only replace or
rename files that they or clients of their organization uploaded.

## Attachments

Drop or paste files into any text field, or use "Attach files": the
file is uploaded and a link (an image shows in place) is inserted into
the text. Files up to 100 MB. Attachments belong to the item whose text
they're in and aren't listed in folders. Who can open an attachment is
who can see the item.

## Visibility

Clients see only what is shown to them: a folder, or a message, doc or
file in the root folder, has the switch, and what is inside a folder
follows it ([Clients](clients.md)). Moving something into a folder
takes on that folder's setting; moving it to the top level makes it
internal.
