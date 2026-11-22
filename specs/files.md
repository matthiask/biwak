# Messages, docs and files

**Status:** built (2026-11-20; tiles, ordering, drag and drop, uploading
several, new docs as drafts, folder colors, a "…" menu on every tile and
"Tell people about it?" with the announcement an hour after the last
change 2026-11-21). `biwak/files/`: attachments
(`attachments.py`), the board (`board.py`), folders and files
(`library.py`, previews in `previews.py`), docs (`docs.py`, titles in
`titles.py`), the operations in `operations.py` (creating in
`biwak/items/operations.py`), `queries.py`, `api.py`. The live editor:
`collaboration.md`. Whom to notify: `notifications.md`. Reactions:
`reactions.md`.

Decided 2026-11-20 ("consistent with the rest"): older doc and file
versions are for staff only (like the item history); moving to the top
level makes the item internal (like new top-level items).

## Storage

Django's storage API (`django-storages`), chosen by `STORAGE_URL`
(speckenv's `django_storage_url`, translated by `biwak/storage_url.py`;
decided 2026-11-20):

- `file:./media/` (the default): `BASE_DIR / "media"`, gitignored, never
  served directly, only through the download views.
- `s3://KEY:SECRET@host/bucket/[prefix/]`: an S3-compatible bucket,
  private, presigned URLs always. The first deployment uses this.
  Options without a translation are an error at startup. No ACLs are set
  on objects (some providers refuse them): the bucket itself must be
  private.
- Paths: `files/<project id>/<random 16 characters>/<file name>`, so
  names never collide and URLs can't be guessed.
- **Files are deleted** with their rows (`post_delete`, after the commit):
  purging the trash, unlinked attachments and deleting a project remove
  the files.
- **Limit:** 100 MB per file (`MAX_SIZE`, decided 2026-11-20; the
  ingress needs the same limit).

## Attachments in texts

Files in to-dos' notes, comments, messages, docs and check-in answers;
they belong to their item and aren't shown in folders.
`Attachment(project, item null, key unique, file, name, size,
content_type, uploaded_by, created_at)`, not an item: its visibility is
its item's.

- **Uploading:** dropping, pasting or "Attach" in a text field
  (`frontend/attachments.js`) posts to `POST /projects/<pk>/attachments/`
  and inserts `![name](attachment:KEY)` (images) or `[name](attachment:KEY)`.
- **Linking:** the operation saving a text links the attachments its
  Markdown references (`attachments.link()`): only those without an item
  yet, in the item's project, uploaded by the person saving. Once linked
  an attachment stays with its item. Unlinked ones are visible only to
  their uploader; `fairy_tasks` deletes them after a day. Lists' and
  projects' descriptions take no attachments.
- **Rendering:** `attachment:KEY` becomes the download URL only for the
  rendered item's own attachments; a reference to another item's (or a
  missing) attachment renders as a plain "attachment", without link or
  name, on pages, in mails and in `*_html`: the name may be internal
  (decided 2026-11-20 after the visibility review). Images inline,
  scaled to the text's width.
- **Trash:** attachments of trashed items can't be downloaded until the
  item is restored (they follow `visible_to()`).

## Downloads

- `GET /attachments/<key>/<name>` and `GET /files/<pk>/download/` check
  visibility first (`Item.objects.visible_to()`; an unlinked attachment
  only for its uploader), then redirect to a presigned URL valid 5
  minutes (bucket) or stream the file (disk).
- The content type comes from the file name, never from the browser.
  Inline: PNG, JPEG, GIF, WebP, AVIF and PDF; everything else is a
  download, SVG and HTML always (they can carry scripts).
  `X-Content-Type-Options: nosniff` always.
- `GET /api/v1/attachments/{key}/download/` serves API tokens (the web
  download needs a session).

## The message board

One per project, `/projects/<pk>/messages/`: pinned ones on top (the
latest pinned first), then newest first, 50 per page by cursor (the
feed's page size), with category, author, date, comment count and the
first two lines (`|excerpt`, `glance.md`). The project page shows the
pinned messages and then the latest, five in all unless more are pinned,
with an "All messages" link (`queries.front_messages()`).

- A message: title, Markdown, optional category, comments, attachments,
  the visibility switch. Categories (`MessageCategory(name, emoji,
  position)`) are one list for the installation, edited by admins in the
  Django admin (decided 2026-11-20).
- **Pinning** (decided 2026-11-20): for everybody, by staff only (the
  operations refuse clients too), any number. `pin_message()` and
  `unpin_message()` set `Message.pinned_at` and record `pinned` and
  `unpinned`, shown in the feed and history, notifying nobody. Trashing
  keeps `pinned_at`.

## Folders

`/projects/<pk>/files/` (the project's "Docs and files") and
`/folders/<pk>/`, with breadcrumbs. The project page lists the five
latest changed docs and files at any depth (`queries.front_files()`) and
the counts of the top level's folders, docs and files.

- **Tiles** (decided 2026-11-21: a grid, not a list in a card,
  `files/_tiles.html`, `.wb-tiles`): an icon by kind or file type, an
  image's preview, the title, the size (files), the checklist signal
  (docs) or what a folder holds directly (decided 2026-11-22: "2
  folders · 1 doc · 3 files", zeros left out, "Empty"; counted for the
  viewer, `queries.folder_counts()`), the client badge; two to five columns by width, compact cards
  in one column on a phone. Empty: "Nothing here yet."
- **A "…" menu on every tile** (decided 2026-11-21: "Folders should
  have a '...' menu for renaming and editing etc.", docs and files too
  for consistency; `files/_tile_menu.html`): a small button in the
  tile's top-right corner, shown on hover and focus, always on touch
  screens, beside the tile's link (not in it), so clicking it doesn't
  open, select or drag the tile, and Tab reaches it after the tile. It
  offers what the item's own "More" menu does, with the same checks
  (the shared `items/_more_entries.html`): Subscribers…, for folders
  Edit… and Order…, for staff on top-level items the visibility switch
  ("Show to clients…", a modal, or "Hide from clients", the same as the
  item's page), Move to… and "Move to trash" for who may
  change it; a client without changes gets Subscribers… only. Its
  modals and the switch come back to the grid (`?next=`,
  `forms.next_url()`, in `folder_edit`, `folder_order`, `switch`,
  `item_move`, `item_subscribers`, `item_trash`). ".." has none.
- **".."** (decided 2026-11-21): inside a folder the first tile leads to
  the parent (the top level from a first-level folder), also a drop
  target.
- **Modals:** "New folder" in the header (title, color, visible to
  clients for staff), "Edit…" in a folder's "More" menu (title and color;
  `library.folder_new`, `folder_edit`, `operations.update_folder()`;
  renaming records `edited`, a color alone no event).
- **Colors** (decided 2026-11-21, as for projects,
  `project-colors.md`): `Folder.color`, a name of the palette or empty,
  chosen with `ColorSwatches` in both modals by whoever may rename. The
  tile's icon area takes the color's tint (`--wb-palette-*-tint-bg`) and
  the folder icon its ink; the folder page's header icon the text color
  (`data-folder-color`, `main.css`). **No color is neutral grey**
  (decided 2026-11-21): the tile, ".." and the header icon take
  `--wb-neutral-bg` and `--wb-neutral-ink`, not the accent, so "no color"
  reads as no color next to colored folders. Not in
  breadcrumbs, mails or the feed. **No suggestion** (decided 2026-11-21):
  new folders start without a color, unlike projects, which are told
  apart by default; the conservative choice, folders are many and a
  color is a choice. API: `color` on `POST projects/{id}/folders/` and
  `PATCH folders/{id}/`; `color` and `color_name` on the folder, `color`
  on folder entries. CLI: `biwak folder new --color`, `biwak folder
  color FOLDER NAME|none`.
- **Ordering per folder** (decided 2026-11-21: stored on the folder):
  alphabetical (the default), reverse alphabetical, newest or oldest
  first, by creation (the last change would reorder while people work).
  Folders always come first, in the same order. Staff set it with
  "Order…" (a modal) in the folder's "More" menu, the top level's in the
  header's menu (`Folder.ordering`, `Project.files_ordering`,
  `FilesOrdering`, `operations.set_ordering()`). Everybody sees that
  order. No event (decided 2026-11-21: just a setting); the audit log
  records the column like any other. No manual order.

### Moving and selecting (decided 2026-11-21)

- **Drag and drop** (`frontend/files.js`): a tile onto a folder tile,
  ".." or a breadcrumb moves it, the same operation as "Move to…"
  (`move_item()`, visibility recomputed; a folder never into itself or
  below). Only tiles the person may move (`can_change()`) are draggable
  and selectable; a refused or failed drop reloads the page.
- **Selecting several** (decided 2026-11-21: no checkboxes, it looks
  nicer, at the price of being less discoverable): Ctrl-click (Cmd on a
  Mac) adds or removes a tile, Shift-click a range, a plain click opens.
  x and Shift+arrows on the focused tile do the same
  (`palette/_shortcuts.html`; decided 2026-11-22: x, not Ctrl+Space,
  which switches input sources on Macs with several layouts; it works
  only on a focused tile, so it stays on with shortcuts off). A bar offers "Move to…", "Move to trash"
  and "Deselect" (Escape too); dragging a selected tile drags them all
  (`library.files_move`, `files_trash` taking `items`;
  `operations.move_items()`, `trash_items()`). A folder trashed with
  something in it goes as one `trashed`, restored together.
- Without JavaScript: "Move to…" per item.

### Uploading files (decided 2026-11-21)

- **"Upload files"** (`library.file_new`) opens a modal with a multiple
  file input; dropping files from the computer anywhere into a folder's
  window opens it for that folder, onto a folder tile, ".." or a
  breadcrumb for that one (`frontend/upload.js`, the drop zone in
  `frontend/files.js`). It lists the files, each with an editable title
  (the extension kept), its size, removable; below, once for all:
  visible to clients (staff, at the top level only), who is told and
  "Also tell…" (as for one file, `notifications.md`). No description (set on the
  file's page).
- **Uploading:** one after another (`library.file_upload`, one file as
  JSON), a progress row each; an error stays on its row, the others go
  on. Then the page reloads (dropped onto a folder tile: you stay).
  Without JavaScript it's a page (`files/upload_form.html`): the files go
  up at once, a too big one is a message.
- **One notification for the batch** (decided 2026-11-21): "Ada uploaded
  5 files to Minutes", one lantern entry and one mail listing the files,
  not one per file. The batch is a random ID made with the form, stored
  as `batch` in the files' `created` events (`create_upload(batch=)`);
  the lantern and the mails merge it (`lantern.md`, `notifications.md`).
  One person's batches into the same folder (or the top level), each
  within 10 minutes of the one before, merge into one entry and one
  mail too (decided 2026-11-21, like the feed); the files of one batch
  stay together however long one takes and whatever came in between
  (another tab's batch; a batch belongs to the chain it started in,
  `lantern.chain()`, one rule for the lantern and the mails, decided
  2026-11-22).
- **A batch's mail waits until it's complete** (decided 2026-11-21,
  the simplest robust way): the modal sends `more` with every file but
  the last it will send (`UploadOneForm`, `create_upload(more=)`,
  stored in the event); `send_mails` holds a group whose newest file
  says `more` until the rest arrived, else for `BATCH_WAIT` (an hour:
  the last file failed or the tab was closed). Without the flag (the
  page without JavaScript sends all files at once) the 10 minutes
  after the newest apply as everywhere. No "done" request: the flag
  rides on the uploads.

## Docs

`/docs/<pk>/`, edited live by anyone who can see them (clients only
docs they created, `can_change()`; `collaboration.md`). The page shows
the content in a card (`card`, `card-body`, like the to-do's page, its
`#live-text` inside), reactions and comments below.

- **The title is the text's first line** (decided 2026-11-21: like a
  blog entry's H1; `titles.doc_title()`): a heading without its `#`s,
  else the line as plain text; cut at a word boundary below the field's
  length with "…"; "Untitled" when empty. Stored as `Item.title`, set in
  `operations._save()`, which every change of the text goes through (the
  live editor, the API, ticks, restoring a version, the importer), so
  lists, the feed, search and mails use it. A changed title is an edit
  like any other. The page header shows the title as its `<h1>`, like
  other items' pages, and the text's first line, when it's a heading, is
  not shown again below it (decided 2026-11-22, replacing "no title in
  the header": screen readers had no heading, phones no title; left out
  when rendering, `checklist_markdown … without_title=True`, decided
  2026-11-22: CSS hiding it missed texts whose task list can be ticked).
  A first line that isn't a heading still shows below the title. The
  live editor's heading is there for screen readers only (the editor shows the first line, which changes as
  people type). Messages keep their subject field. `create_doc()` (the API,
  the importer) puts `# <title>` and an empty line in front
  (`with_heading()`); the importer's second run doesn't add it twice.
- **Versions:** `DocVersion(doc, title, content, created_by,
  created_at)`; the newest always equals the doc. A save updates it when
  by the same person within 10 minutes, else starts a new one; "Save as
  a version" always does (decided 2026-11-20). Unchanged saves do
  nothing. Restoring saves the old title and content as a new version.
  A whole-text save over somebody else's newer version is refused
  (`base_version`, 409 in the API; also within the other's ten-minute
  window).
- **New docs are drafts** (decided 2026-11-21): "New doc" is a link
  making a draft and opening the editor with `# ` and the cursor after
  it (`items.operations.create_draft()`: title "Untitled", no event, no
  version, its creator subscribed). A draft (`Item.is_draft`) is
  nobody's business until written: `visible_to()` leaves it out, and
  `drafts=True` lets its creator's own in for the editor's pages and its
  websocket only. The first text beyond `#`s and blanks (`is_blank()`)
  makes it a doc in `_save()`: `created_at` then, a quiet `created`
  event (the folder's subscribers aren't told, people mentioned in it
  are), and the browser replaces the address (`data-collab-draft`).
  Empty drafts are deleted after a day (`delete_drafts` in
  `fairy_tasks`), each checked again with its rows locked (decided
  2026-11-21): one published meanwhile stays, so does one with typing
  not merged yet (`LiveUpdate` rows; the next run tries again), and an
  open editor of a deleted draft is told (`live.check_access()`). Nothing reuses drafts (two tabs could share one);
  "Done" on an empty draft goes back to its folder. A draft in a folder
  visible to clients is visible to them once written, as the folder
  says.
- **Telling people once** (decided 2026-11-21): the creator's first
  "Done" saves and asks "Tell people about it?" (`Doc.tell_pending`,
  `docs.doc_tell`): who is told by default and "Also tell…" with a
  note (additive, `notifications.md`, decided 2026-11-21); "Tell them
  too" records `shared` to both, "No one else" to those told by default
  only (the buttons say that the others are told anyway, decided
  2026-11-21)
  (nothing when there's nobody), and either way it's never asked again
  (`operations.tell()`, the doc's row locked and checked). Escape or
  Cancel doesn't answer, the next "Done" asks again. Only the creator is
  asked.
- **No "Done" still tells** (decided 2026-11-21): a doc begun as a
  draft whose creator never answered tells those who want to hear once
  it had no change for an hour (`TELL_AFTER`), as "No one else" would
  (`shared`, the creator as the actor), and then isn't asked any more.
  `send_mails` runs `tell_unanswered()` every minute (`fairy_tasks` is
  daily, too slow); each doc locked with `skip_locked` and checked
  again, so two runs or the creator's answer can't tell twice; typing
  not merged yet (`LiveUpdate` rows) waits for the next run; drafts and
  trashed docs are left alone. Restoring one from the trash counts as a
  change, so it's told an hour later (decided 2026-11-21: trash is
  trash, but not a way around telling), also when it comes back with its
  folder (`restore()` sets `updated_at` on everything it brings back,
  decided 2026-11-22).
- The API and CLI create docs with title and text, not as drafts.

## Files

`Upload(Detail)` with a description, `FileVersion(upload, file, name,
size, content_type, uploaded_by, uploaded_at)`, the newest current.
Parents: the top level or a folder; switchable at the top level;
commentable. `/files/<pk>/`: name, preview, description, comments,
versions.

- The title is the file's name when uploaded and stays when a version
  is replaced; each version has its own name. "Replace" uploads a new
  version (URL, comments and earlier versions stay) and records
  `edited`.
- **Previews:** a WebP thumbnail 400 pixels wide (smaller images aren't
  enlarged) of images (Pillow) and PDFs' first page (pypdfium2, no
  system packages), made on the first request and stored as
  `preview/preview.webp` in the file's directory (decided 2026-11-20).
  Broken files have none (404, logged). Only the current version's.

## Who may change what

- Staff create folders, docs and files; clients don't (decided
  2026-11-20 after the visibility review, `access.md`).
- Clients edit only docs they created (decided 2026-11-20: a client
  could otherwise rewrite an agreed brief), replace or rename only files
  they or clients of the same organization uploaded (`User.organization`
  set and equal, decided 2026-11-21), and move only what they may change.
  A client's item moved to the top level becomes internal.
- Older versions of docs and files (pages, API, downloads) are staff
  only: they can hold what was internal before the item was shown.
- Mentions in messages, docs and files: the forms offer `@` (new ones
  ask the project who will see them, `notifications.md`); the API
  resolves `@ada@example.org` and an unambiguous `@Ada`.

## API and CLI

`POST /api/v1/projects/{id}/attachments/` (multipart `file`, answering
the key and the Markdown), `GET /api/v1/attachments/{key}/`; messages
(list, create with `also`, update, pin), folders (contents, create,
move, `PATCH folders/{id}/` with `title` and `ordering`), the top level
(`GET`/`PATCH projects/{id}/files/` with `ordering`), docs (get, update
with `base_version`, versions; a `title` alone is a 400, the title is the
text's first line), files (upload, replace, versions, download URL).

CLI: `--attach FILE` on commands writing texts (appended at the end),
`biwak messages`, `biwak message show|post`, `biwak files [FOLDER]`
(with "Order:"), `biwak folder new|move|rename|color|order`, `biwak file
upload|download`, `biwak doc show|edit` (`$EDITOR`).
