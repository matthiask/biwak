# The lantern and live updates

An in-app inbox for notifications, the **lantern** (named 2026-11-21,
after Biwak's camp theme; avoiding "Hey!", the name of Basecamp's mail
product; its icon is a torch with its light, `frontend/styles/icons.css`),
and pages that update while they're open.

**Status:** built (2026-11-21).

## Decided (2026-11-21)

- The lantern shows the same notifications as the mails, with the same
  levels: whatever you'd be told about. Mail is a delivery choice:
  **each**, **digest** or **none** ("No mails", `MailDelivery.NONE`).
- **Read in the lantern, not mailed:** a notification read before its
  mail goes (the 10-minute merge window, or before the digest) is left
  out of it; a mail or digest with nothing left isn't sent.
- **Live** on item pages (to-dos, messages, docs, files, check-in
  questions), lists and the board, reactions included. Not the feed or
  the project page. What's new slides in quietly; nothing moves what
  you're reading or typing in.
- **Browser notifications** (Web Push): mentions and assignments only,
  `web-push.md` (built 2026-11-22).

## The lantern

`biwak/activity/lantern.py`, the views in `biwak/activity/views.py`
(`/lantern/`, `/lantern/menu/`, `/lantern/count/`), `frontend/lantern.js`,
`GET /api/v1/lantern/`, `POST /api/v1/lantern/read/`, `biwak lantern`.

- **The menu** (`base.html`, fetched from `/lantern/menu/` when opened;
  `frontend/lantern.js` fetches the count on every page and when told):
  bookmarked items first, then the unread entries (at most 100, the page
  has all), then the latest 30 read ones, newest first, grouped by item
  ("Mark all as read", a link to the page). **One entry per item**
  (decided 2026-11-23: an item read once and told about again showed
  twice): an item with unread notifications has its read ones among
  those 30 in its entry among the unread, quiet, not a second entry
  among the read. No "Read" and "Unread"
  headings; one divider between groups (the items' borders, no `<hr>`).
  `min(34rem, 100vw - 2rem)` wide, placed by `menus.js`; on a phone it
  spans the screen below the bar. Without JavaScript the button links to
  `/lantern/`.
- **An entry:** the item's title, kind icon and project (no client badge:
  calmer, and the item's page shows it, decided 2026-11-21); what
  happened, in the mails' words (`mails.describe()`), with the excerpt
  where there is one; when. An item with unread notifications has a red
  dot before its title (`--wb-lantern-dot`, `.wb-lantern-unread`); read
  ones are quiet (secondary color, not bold), in the menu and on the
  page.
- **The count is the number of items** with unread notifications, not
  of notifications (decided 2026-11-21: the menu groups by item): the
  button shows a small red dot without a number, the number is in its
  tooltip and screen-reader text and `/lantern/count/`
  (`unread_count()`; `unread_counts()` gives both). The API answers
  `unread` (notifications) and `unread_items` next to `results`;
  `biwak lantern` prints one row per item ("(+N)" for more), `--json`
  the entries. Digests are unaffected.
- **A batch of uploaded files is one entry** (`entry_key()`, `Batch`;
  `files.md`, "Uploading files"), and so are one person's batches into
  the same folder (or the top level) each within 10 minutes
  (`MERGE_AFTER`) of the one before (`group_batches()`, decided
  2026-11-21), and a batch's files however far apart (decided
  2026-11-22; `chain()`, the mails' rule too): its folder, "Ada uploaded 5 files to
  Minutes.", the files linked; counted once; following it, "Mark as
  read" and "Mark as unread" act on all its files. No bookmark button:
  bookmarks are per item.
- **Completing and reopening back and forth** (decided 2026-11-21): of
  the unread notifications, those of a person's consecutive completing
  and reopening of an item don't show when they cancel out; otherwise
  only the last shows (`mails._deliverable()`, `notifications.md`).
  Read ones show as they were. The item's other unread completing and
  reopening count too (`mails.done_neighbours()`, decided 2026-11-22), so
  the page's edges and the menu's limit don't split a pair. They cancel
  out also when one was mailed already: someone may have got both mails
  while the lantern shows neither, by design (`notifications.md`).
- **The page** `/lantern/`: the same, paginated like the feed, filters
  "unread" and "mentions only".
- **Bookmarking** (decided 2026-11-21; "Bookmark", not "Pin", which
  stays the board's): an entry's item can be bookmarked (the existing
  bookmarks, `lantern.bookmark()`, `unbookmark()`); bookmarked items with
  notifications are in "Bookmarked" at the top of the menu and the page,
  with their latest notification read or not, and not in the other
  sections. The latest is the latest left after completing and
  reopening cancelled out among the unread ones. A bookmark made on the
  item's page counts too. The API's entries say `bookmarked`.
- **The favicon** (decided 2026-11-21): with `User.lantern_in_favicon`
  (on by default, in the settings' notifications section) the tab's icon
  shows a dot while something is unread, updated live, drawn on a
  canvas.
- **Visibility:** listing applies the mails' rules
  (`notifications_for()`, `wanted()`, `mails._deliverable()`): only items
  the person sees now, for clients only events of the time clients saw
  the item (the level doesn't hide anything: subscribing is the switch,
  `notifications.md`). Others stay in the database, unseen. Pages may
  hold fewer entries than asked for (visibility and the net change of
  completing and reopening are checked after loading). Reading and marking unread touch only what's
  listed.

### Reading

- **Only the lantern reads** (decided 2026-11-21): following an entry, "Mark as read", "Mark all as
  read", and acting on the item (below). Opening the item some other way
  (the feed, a list, a mail, a live update) reads nothing.
- **Entries are links** (decided 2026-11-21: the address shows on
  hovering and opens in a new tab) to the item, at the comment where it
  applies. A click or middle click posts `/lantern/<id>/`
  (`views.lantern_open`) in the background (`keepalive`), which reads
  the whole item's notifications (its comments' too) and answers 204. The
  view only takes POST with the CSRF token, so another site can't read
  somebody's notifications. Without JavaScript, or "Open in new tab"
  from the context menu, nothing is read: "Mark as read" covers that.
- **Home's rows** with unread notifications (`dashboard.md`) are the
  lantern's entries on another page and read the same way.
- **Mark as unread** per item brings back the notifications read
  together with its latest one, so the entry is unread as a whole.
  **Marked unread means no mail** (decided 2026-11-21): such a
  notification is never mailed afterwards
  (`Notification.marked_unread_at`); an edit merged into it stays
  unmailed, a new event is mailed as usual. An edit merged into it that
  mentions them for the first time since is mailed and pushed (decided
  2026-11-28: a first mention tells, `notify._tell()`).
- **Switching mail back from "none":** whatever is unread and wasn't
  marked unread by hand goes with the next mail or digest.
- A merged edit moving an unsent notification forward makes it unread
  again: the change is new.

### Reading by acting (decided 2026-11-21)

Acting on an item reads its notifications for the person acting:
having done something with it means having dealt with it, so nobody
ticks the same thing off twice. **When in reasonable doubt, it stays
unread.**

- **Reads:** completing or reopening a to-do; editing any kind of item
  (only when something actually changed: the to-do's fields, also
  several at once with "Due date…" and "Assign…", each to-do it
  changed, `assign_todos()` since 2026-11-28,
  `update_message()`, `update_upload()`, `replace_upload()`,
  `update_list()`, `update_answer()`, `update_question()`; a doc's saved
  change reads for each of its authors in `_save()`); ticking a
  checklist item; commenting (pages, API, mail replies); adding a
  reaction to the item, one of its comments or its completing; answering a check-in
  question (the question's and the person's own answer's notifications,
  not other people's answers). A direct mention among them is read too.
- **Doesn't read:** having the item open, scrolling, a live update,
  opening it from anywhere but the lantern, bookmarking ("later", the
  opposite of dealt with), subscribing, moving, reacting with a reaction
  that's there already, removing one, pausing a question, pinning,
  changing a project, anything done to the list or project around it.
- Only that item's notifications (with its comments'); the others'
  stay as they are. `read_by_acting(actor, *items)` in
  `biwak/activity/operations.py`, called by the operations, so pages,
  the API, the CLI and mail replies behave alike; it does nothing inside
  `importing()` (the importer, `fairy_tasks` and the next recurring
  to-do aren't the person acting).

### Assigned and mentioned in one change (decided 2026-11-21)

One notification, the assignment: "Ada assigned you (and mentioned
you)." The mention adds nothing on top (Basecamp sends two, which is
annoying). `items.operations.assign(mentioned=…)`, called by
`create_todo()` and `update_todo()`, moves those both assigned and
mentioned from the event's `mentioned` to `assigned`, which
`notify.candidates()` leaves out. Mentions in a later edit or a comment
notify as usual; assigned-only people get `created` and `assigned` as
before.

## Live updates

One websocket per browser tab, `/ws/live/?item=ID` (Channels, the same
ASGI setup as `collaboration.md`; `biwak/live/consumers.py`,
`frontend/live.js`). The doc's editor page has none (one
socket per tab: the editor's); its lantern count is fetched on load.

- **Never content through the websocket.** Messages carry IDs and the
  kind of change, never text or names. The page fetches itself through
  its normal view and takes over its regions (`[data-live]` replaced,
  children of `[data-live-list]` added, removed, reordered), so every
  fragment goes through the page's permission checks and a client gets
  404 for anything internal.
- **Access:** joining checks `visible_to()` (4404 like the pages' 404,
  4401 without a login). The item's group is the staff one or the
  clients' one (`announce.item_group()`); an announcement goes to the
  clients' group only if it happened while clients saw the item. The
  socket checks access again before passing on every announcement and
  ping (decided 2026-11-21: no window at all if an `access.check`
  message is lost), on `access.check` and every 60
  seconds; made a client meanwhile, it switches groups. Logging out
  closes the session's sockets at once (4401), logging out everywhere
  those of the others.
- **Announcements** (`biwak/live/announce.py`), after the commit only:
  every event of an item (`record()`) tells the pages of the item and
  its parent; reordering, the lists a to-do left, groups changed and
  reactions removed are told explicitly. The lists a to-do left are told
  by their own visibility: a client's page of a list whose to-do moved
  into an internal one hears "reordered" (of its own list, never naming
  the other) and loses the row (fixed 2026-11-28, verification round 1). The person's own group gets
  lantern pings (`lantern_changed()`), only for events about items they
  see then, for clients only of the time clients saw the item (the same
  filter as `notify()`'s). The actor's own pages aren't told.
- **What changes:** on item pages comments, reactions, completing and
  reopening, the title and text (when not editing them oneself),
  assignees, the due date, trashing ("This isn’t here anymore: it was
  trashed, or you can’t see it anymore.", with a link back); on lists
  and the board to-dos added, completed, reopened, renamed, moved,
  reordered, trashed, and reactions on rows.
- **Not disturbing:** new things slide in with a short highlight
  (`.wb-live-new`); the scroll stays; a region with focus in a field, a
  changed field, an open `<details>` or an open peek waits with "Changed
  meanwhile: shown once you save or close this." and takes over once
  left; several changes within 300 ms are fetched once.
- **Only real changes are marked** (decided 2026-11-28, GitHub issue
  #2): a region counts as changed when the server renders it
  differently from before (`frontend/live-rendered.js` keeps what it
  rendered, before any script adds its toolbar, mentions or editor to
  the forms); one the page changed itself (a form submitted, a field
  changed, an htmx request) is compared with what it shows. **Back in
  the history** (a page restored from the back/forward cache) the page
  fetches itself and takes over what changed meanwhile without marking
  anything, as a reload would show it.
- **Reconnecting** fetches the page once. Without JavaScript or
  websockets everything works as before. No polling.
- **Limits:** `?item=` longer than 18 digits closes with 4404; at most 50
  websockets per person and process (`MAX_PER_PERSON`, confirmed
  2026-11-21, to be tuned after real use), more close with 4429 and the
  page reconnects later, backing off. The live editor's limits are in
  `collaboration.md`.
