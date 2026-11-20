# Messages, docs and files

**Status:** stage 1 built (2026-11-20): `biwak/files/` (the
`Attachment` model, `attachments.py` with the operations, upload and
download views, `api.py`), storage settings, `frontend/attachments.js`,
`--attach` on `biwak todo add|edit|comment`. Stage 2 built (2026-11-20,
branch `files2`): the file kind (`Upload` in `biwak/items/models.py`,
`FileVersion` in `biwak/files/models.py`), message categories (Django
admin), `Message.pinned_at`, doc versions and locks; operations in
`biwak/files/operations.py` (creating is in `biwak/items/operations.py`);
pages in `board.py` (messages), `library.py` (folders, files, previews
through `previews.py`) and `docs.py`; the API in `api.py`, CLI 0.10.0.
Decisions and open questions of the building agent are under "Details
of stage 2".

**Agent:** stage 1 with a strong model (downloads are an entry point for
visibility); stage 2 suits a cheaper model following this spec and the
checklist in `AGENTS.md`.

**Depends on:** stage 1 of `notifications.md` (choosing whom to notify,
mentions in texts).

## Stage 1: storage, uploads, attachments, downloads

### Storage

Through Django's storage API (`django-storages`), chosen by settings
(decided 2026-11-20):

- **`STORAGE_URL`** in the environment, read with speckenv's
  `django_storage_url` (decided 2026-11-20), translated for
  django-storages by `biwak/storage_url.py`:
  - `file:./media/` (the default): `FileSystemStorage` in
    `BASE_DIR / "media"`, gitignored. Development, tests, small
    installations. The folder is never served directly, only through
    the download views below.
  - `s3://KEY:SECRET@host/bucket/[prefix/]` for an S3-compatible bucket:
    `S3Storage`, private, presigned URLs (always, whatever the URL's
    `aws_s3_bucket_auth` says). The first deployment uses this. Options
    without a translation are an error at startup.
- Other backends (e.g. a Google Drive shared drive) are possible later;
  without presigned URLs, downloads go through the app.
- Paths: `files/<project id>/<random 16 characters>/<file name>`, so
  names never collide and URLs can't be guessed.

Sizes from a real Basecamp account of a small agency, for orientation: a
few hundred GB after eight years, about 40 GB a year, most of it
screenshots and PDFs attached to comments.

### Attachments in texts

Files in to-dos' notes, comments, messages, docs and check-in answers.
They belong to their item and aren't shown in folders.

- **Model:** `Attachment(project, item null, key unique, file, name,
  size, content_type, uploaded_by, created_at)`. Not an item: its
  visibility is its item's.
- **Uploading:** dropping or pasting files into a text field, or its
  "Attach" button (`frontend/attachments.js`), posts to
  `POST /projects/<pk>/attachments/` and inserts the Markdown at the
  cursor: `![name](attachment:KEY)` for images, `[name](attachment:KEY)`
  for everything else. The attachment has no item yet.
- **Linking:** the operation saving the text links the attachments its
  Markdown references to the item (`attachments.link(item, text)`).
  Unlinked attachments are visible only to who uploaded them;
  `fairy_tasks` deletes those older than a day.
- **Rendering:** the Markdown filter turns `attachment:KEY` into the
  download URL; images show inline, scaled to the text's width.
- **Limit:** 100 MB per file (decided 2026-11-20; the ingress needs the
  same limit).

Details of stage 1 (proposed by the building agent, 2026-11-20; change
them here if wrong):

- **Who links what:** saving a text links only attachments without an
  item yet, in the item's project, uploaded by the person saving the
  text. Once linked, an attachment stays with its item, also when the
  text no longer references it; referencing it in another item's text
  doesn't move it (people who see only the other item get a 404).
- **Where:** linked when to-dos' notes are created or changed, comments
  added, messages and docs created (their edit operations come with
  stage 2 and call `attachments.link()` too). Lists' and projects'
  descriptions take no attachments. The "Attach files" button is on the
  to-do page (notes and comments) and the inline form adding to-dos; the
  to-do page now shows the rendered notes above the form.
- **Trash:** attachments of trashed items can't be downloaded (they
  follow `Item.objects.visible_to()`, which leaves out trashed items)
  until the item is restored.
- **Type:** the content type comes from the file name, never from what
  the browser sends. Inline (and shown as images in texts): PNG, JPEG,
  GIF, WebP, AVIF and PDF (inline only); everything else is a download.
- **Unknown keys** (deleted attachments) render as links to `#`.
- **Files are deleted** with their rows (a `post_delete` signal, after
  the transaction commits), so purging the trash, deleting unlinked
  attachments and deleting a project all remove the files.
- **API:** besides the two endpoints below, `GET
  /api/v1/attachments/{key}/download/` serves the file to API tokens
  (with a bucket a redirect to a presigned URL), since the web download
  needs a session. `--attach` appends the Markdown at the end of the
  text; `biwak todo edit --attach` appends to the current notes.
- **Bucket:** no ACLs are set on objects (`default_acl` None, some
  providers refuse them): the bucket itself has to be private.

### Downloads

- `GET /attachments/<key>/<name>` and, in stage 2, `GET
  /files/<pk>/download/` check visibility first (the item through
  `Item.objects.visible_to()`; an unlinked attachment only for its
  uploader), then:
  - with a bucket: redirect to a presigned URL valid 5 minutes;
  - on local disk: stream the file (`FileResponse`).
- Images and PDFs inline (`Content-Disposition: inline`), everything else
  as a download. `X-Content-Type-Options: nosniff` always; SVG and HTML
  always as downloads, never inline (they can carry scripts).

### API

`POST /api/v1/projects/{id}/attachments/` (multipart, field `file`,
returns key and the Markdown to insert), `GET /api/v1/attachments/{key}/`
(metadata and a download URL). The CLI's commands that write texts take `--attach
FILE` (repeatable).

### Done when (stage 1)

- Uploading, inserting, linking on save, rendering, downloading, on local
  disk and with a bucket (the bucket mocked in tests, e.g. with
  `moto` or by checking the redirect).
- Visibility through every path: a client gets 404 for an attachment of
  an internal to-do, also by its key; an attachment's visibility
  follows its item when the item moves or its list's switch changes;
  unlinked attachments only for their uploader.
- `fairy_tasks` removes unlinked attachments after a day; deleting an
  item for good (trash) deletes its attachments' files.

## Stage 2: message board, folders, docs, files

### Model

- **Kind `file`** (new): `Upload(Detail)` with a description (Markdown);
  `FileVersion(upload, file, name, size, content_type, uploaded_by,
  uploaded_at)`, the newest is the current one. Allowed parents: none
  (the root folder) or a folder. Switchable at the top level,
  commentable.
- **Message:** `Message` gets `category` (foreign key to
  `MessageCategory(name, emoji, position)`, optional) and `pinned_at`.
  The categories are one list for the installation, edited by admins in
  the Django admin (decided 2026-11-20).
- **Doc:** `Doc` gets `locked_by` and `locked_at`;
  `DocVersion(doc, title, content, created_by, created_at)`.

### Message board

One per project: `/projects/<pk>/messages/`, newest first, pinned ones on
top, with category, author, date and the number of comments.

- A message: title, Markdown, optional category, comments, attachments,
  pinned or not, the visibility switch.
- Posting asks whom to notify: everybody in the project (the members at
  that moment), chosen people, or nobody (`notify_people()`,
  `notifications.md`).
- Pages: the board, `/messages/<pk>/` with comments, new and edit forms.
  The project page shows the pinned messages and then the latest ones,
  three in all unless more are pinned.
- Board rows show the first two lines of the message (`|excerpt`,
  `glance.md`; add the filter as described there if it isn't merged).
- **Pinning** (decided 2026-11-20): pinned for everybody, by staff only
  (like the visibility switch; clients see pins but can't set them).
  Any number; pinned ones on top, the latest pinned first, then the
  rest newest first. Operations `pin_message()` and `unpin_message()`
  set `pinned_at` and record `pinned` and `unpinned` events (shown in
  the feed and the history, notifying nobody). A pin button on the
  message's page and in the board's row menu. Trashing keeps
  `pinned_at`, so restoring brings the pin back.

### Folders, docs and files

- The project's root: `/projects/<pk>/files/`, then `/folders/<pk>/`:
  folders first, then docs and files, by title, with breadcrumbs.
- Create folders and docs, upload files, move them between folders
  (`move_item()`, which resets the switch when nested), the visibility
  switch on top-level ones (children inherit it).
- **Docs** (`/docs/<pk>/`): title and Markdown, comments, edited by
  anyone who can see them.
  - **Versions:** saving creates a version when the last one is older
    than 10 minutes or by someone else, plus "Save as a version" on
    request (decided 2026-11-20). Older versions can be viewed and
    restored (restoring saves the old content as a new version).
  - **Lock** until real-time editing (`collaboration.md`): opening the
    edit form takes the lock; the page renews it every minute
    (`POST /docs/<pk>/lock/`); it expires 5 minutes after the last
    renewal. Others see "Ada is editing" and can read; after the lock
    expired they can edit, and saving over someone else's newer version
    is refused with a link to compare.
- **Files** (`/files/<pk>/`): name, preview, description, comments,
  versions. "Replace" uploads a new version: the URL, comments and
  earlier versions stay.
- **Previews:** a WebP thumbnail 400 pixels wide for images (Pillow) and
  PDFs' first page (pypdfium2, no system packages), made on the first
  request and stored next to the file (decided 2026-11-20).

### API and CLI

Endpoints for messages (list, create with whom to notify, update, pin),
folders (contents, create, move), docs (get, update with the version
rules, versions), files (upload, replace, versions, download URL).
`biwak messages`, `biwak message show|post`, `biwak files [FOLDER]`,
`biwak file upload|download`, `biwak doc show|edit` (edit opens
`$EDITOR` and saves on exit).

### Done when (stage 2)

- Pages, API and CLI for all of the above, with the client badge and
  banner on visible items.
- Tests: visibility of files, docs and messages through pages, previews,
  downloads, API and the board; moving a folder changes its contents'
  visibility; doc versions and locks (expiry, refusing to overwrite a
  newer version); file versions keep comments and URL.
- Pinning: the board's and the project page's order, a client can't pin
  (page and API), the events notify nobody.

### Details of stage 2

Proposed by the building agent (2026-11-20); change them here if wrong.
Marked **?** are questions the spec didn't answer, built the safe way.

- **Whom to notify (?)**: the forms, the API (`notify`: `everybody`,
  `nobody` or IDs) and the CLI (`--notify`) have no default: posting a
  message, doc or file asks every time. `create_message()`,
  `create_doc()` and `create_upload()` default to `nobody`.
- **Older versions are for staff (?)**: the doc versions' pages and API,
  the older versions of files and their downloads. Like the history,
  they can hold what was internal before the item was shown to clients.
  Clients see and edit the current doc, and download the current file.
  A client's refused save over a newer version names who saved it but
  has no link to compare.
- **Doc versions:** the newest version always equals the doc. Saving
  updates it when it is by the same person and not older than 10
  minutes, else starts a new one; "Save as a version" always starts a
  new one. Restoring saves the old title and content as a new version.
  Unchanged saves do nothing. The title is part of a version.
- **Doc locks:** opening the edit form takes the lock (someone else
  holding it is sent back to the doc with "Ada is editing"); the form
  renews it every minute (`frontend/doc-lock.js`); it expires 5 minutes
  after the last renewal. Saving gives the lock up (**?**), so does
  Cancel (a POST to `/docs/<pk>/lock/` with `release`). Saving or
  restoring while someone else holds an unexpired lock is refused.
  Refusing a stale save: the form carries `base_version` (the newest
  version when it opened); a newer version by somebody else refuses the
  save, newer ones by the same person don't. The API's `base_version` is
  optional. The lock columns are left out of the audit log (renewed
  every minute).
- **Files:** the title is the file's name when uploaded and stays when a
  new version is uploaded (**?**), the version has its own name.
  Clients upload where they see and replace or rename only what they
  uploaded; staff everything. Replacing records `edited` (with the new
  version's name).
- **Previews:** 400 pixels wide as specified, images already smaller are
  not enlarged (**?**); broken files have none (404, logged). Only the
  current version has a preview on the page.
- **Folders:** anyone who sees where creates folders, docs and files
  (what clients create is visible). Moving: `can_change()` (clients only
  what they created), into folders the person sees, a folder never into
  itself or below itself. A client's item moved to the root gets the
  root's default (internal), as the switch is off there (**?**).
- **Board:** 25 messages per page besides the pinned ones (all on the
  first page), "Older messages" pages by cursor (**?**); the API pages
  with cursors, pinned first. The project page shows only counts of the
  root's folders, docs and files under "Docs and files" (**?**).
- **Pinning:** `pinned` and `unpinned` are events like the others but
  `notify()` skips them; the pin operations refuse clients themselves
  too.
- **Mentions:** the edit forms and comments offer `@`; the new forms have
  no item to ask yet, so typed `@` completion is missing there (the
  syntax still works), and the API's create endpoints take the syntax
  only (plain `@names` are resolved on update).
- **Dependencies:** Pillow and pypdfium2 (pure wheels, no system
  packages).
