# Messages, docs and files

**Status:** open. The item kinds `message`, `folder` and `doc` and their
detail models exist (core), without pages.

**Agent:** stage 1 with a strong model (downloads are an entry point for
visibility); stage 2 suits a cheaper model following this spec and the
checklist in `AGENTS.md`.

**Depends on:** stage 1 of `notifications.md` (choosing whom to notify,
mentions in texts).

## Stage 1: storage, uploads, attachments, downloads

### Storage

Through Django's storage API (`django-storages`), chosen by settings
(decided 2026-11-20):

- **Local disk** (`FileSystemStorage` in `BASE_DIR / "media"`,
  gitignored) when no bucket is configured: development, tests, small
  installations. The folder is never served directly, only through the
  download views below.
- **An S3-compatible bucket** when `STORAGE_BUCKET` (plus endpoint, key
  and secret) is set in the environment: `S3Storage`, private, presigned
  URLs. The first deployment uses this. Same code, only settings differ.
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

`POST /api/v1/projects/{id}/attachments/` (multipart, returns key and
the Markdown to insert), `GET /api/v1/attachments/{key}/` (metadata and
a download URL). The CLI's commands that write texts take `--attach
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
  The project page shows the three latest messages.

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
