# Messages, docs and files

## Message board

One per project. Messages: title, rich text, optional category, comments,
attachments, pinned or not. Listed newest first, pinned on top. Posting
a message can notify chosen people or everybody in the project.

## Docs and folders

- Folders nest. The project's root folder holds folders, docs and files.
- A doc: title and rich text, comments, edited by anyone who can see it.
  Versions are kept (each save with a gap of some minutes, plus on
  request); older versions can be viewed and restored.
- Real-time editing comes later (`collaboration.md`); until then, a doc
  is locked while someone edits it (the lock expires, others see who has
  it).

## Files

- Uploads into folders, with a description and comments. Replacing a file
  keeps its URL and comments and keeps the earlier versions.
- Attachments in rich text (to-dos, comments, messages, docs) are files
  too, belonging to their item.
- Previews: thumbnails for images and PDFs, generated once and stored.
- Downloads with short-lived signed URLs from the storage backend, after
  the visibility check.

## Storage

Through Django's storage API (`django-storages`), so the backend can
change:

- **Default: S3-compatible object storage**, private bucket, presigned
  URLs.
- **Other backends** possible, e.g. a Google Drive shared drive with a
  service account. Without presigned URLs, downloads then go through the
  app. Not part of the first version.

Sizes from a real Basecamp account of a small agency, for orientation: a
few hundred GB after eight years, about 40 GB a year, most of it
screenshots and PDFs attached to comments.

## Tests

Visibility of files through every path (page, attachment URL, preview,
API, mail); versions; folder moves changing visibility.
