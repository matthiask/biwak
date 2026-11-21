# People: profile images and a page per person

Today people appear as names only. A face, or at least a colored mark,
makes lists, comments and the lantern quicker to scan, and the People
page (`organizations.md`) wants something to show per person.

**Status:** stage 1 built (2026-11-21), see "Built" below; stage 2 open
(waits for the drawings).

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`; have the image's visibility reviewed.

**Depends on:** `organizations.md` merged (the People page, partners'
`known_to`), `files.md` stage 1 (storage, download views).

**Touches:**
- `biwak/accounts/` (the image field, the operations, the settings
  section, the view serving images);
- one `{% avatar person %}` tag and its include;
- the templates that show people (see "Where");
- `biwak/importer/` (stage 1);
- the API and CLI;
- CSS.

## Stage 1: the mark and uploaded images

- **The mark:** every person gets one mark, `{% avatar person size %}`,
  used everywhere a person is shown in a list or next to their words.
  - With an image it shows the image.
  - Without one it shows the initials on a color of the palette
    (`keyboard.md`'s ten names). The color is chosen from the person's
    id, so it stays the same and needs no setting.
  - Sizes: small in rows and pills, larger on the People page and the
    person's page.
  - The full name is in the `title` and in the image's `alt`.
- **Uploading:** in the settings, a "Profile image" section, the first
  under Appearance.
  - JPEG, PNG or WebP, at most 5 MB.
  - Stored once, cut to a square in the middle and scaled to 256 pixels,
    as WebP, through the storage of `files.md`. Pillow is already a
    dependency.
  - "Remove" goes back to the initials.
  - People change their own image. Admins can remove anyone's (for an
    unfitting image), recorded in the audit log.
- **Serving:** through a view, like downloads, never from the storage
  directly.
  - The image is visible exactly where the person's name is: to whoever
    may know the person (`known_to`, `people_known_to`; clients and
    partners only see members of their projects).
  - Long cache headers, and a version in the URL that changes with the
    image.
- **Where:**
  - the People page and the person's page;
  - comments and messages (the author);
  - feed entries and the lantern (who did it);
  - assignee pills and the `@` list;
  - subscribers and members;
  - check-in answers;
  - the live editor's names of the others.

  Not in mails: images in mails need public URLs, and many mail programs
  block them anyway.
- **The person's page** (`/people/<id>/`): the large mark, name,
  organization, role, and the projects both people are in. It links
  the person's feed (`person_feed`), which today is the only page per
  person. The People page links here. Visible to whoever may know the
  person, else 404.
- **Importer:** Basecamp's people carry an `avatar_url`. It's imported
  once, when the Biwak person has no image yet, and never overwrites an
  image set in Biwak. Basecamp's own generated initials images are
  skipped if they can be told apart (the agent checks a real account's
  data: they may differ in URL or headers). If they can't, they're
  skipped entirely, since our own mark is better than an imported one.
- **API and CLI:**
  - People in the API carry `image_url` (or null).
  - `PUT /api/v1/me/image/` (multipart) and `DELETE` for removing it.
  - `biwak me image FILE` and `biwak me image --remove`.

### Done when (stage 1)

- The tag, upload, removal, serving with the visibility rule, and the
  importer, each with tests as staff, partner and client. That includes a
  client getting 404 for the image of someone they don't know.
- The mark in the places listed.
- The person's page.
- The API and CLI.

## Stage 2 (later): choosing from a set of images

Instead of uploading, people pick one of a small set of drawn images
fitting Biwak's theme: a tent, a mountain, a lake, a fir, an ibex, a
marmot, …, each on a palette color. The set ships with the app (SVG);
choosing stores its name. This waits for the drawings.

## Decided (2026-11-21)

- The default mark is the initials on a palette color chosen from the
  id, with no setting.
- Basecamp's profile images are imported once and never overwrite one
  set in Biwak.
- Each person gets a page with the projects in common.
- Admins can remove someone's image, recorded in the audit log.

## Built (stage 1, 2026-11-21)

- **The field and the operations** (`biwak/accounts/`): `User.image`, the
  storage name `people/<id>/<version>.webp` (the version is a random key
  that changes with every upload, `User.image_version`); no table of its
  own, the person's row is in the audit log, which records removing.
  `operations.set_image()` (own image only: not even admins set another's),
  `remove_image()` (own, or any by admins) and `image_data()`, which cuts
  the middle square, scales to 256 pixels and saves WebP; JPEG, PNG and
  WebP, at most 5 MB, anything else is `InvalidImage`. The old file goes
  after the commit.
- **Serving** (`accounts.views.person_image`,
  `/accounts/people/<id>/image/<version>.webp`): for whoever
  `organizations.people.known_people(viewer)` lists, which the People page
  uses too (own staff everybody, partners and clients members of their
  projects, and themselves), else 404; also 404 for an old version.
  `Cache-Control: private, max-age=1 year, immutable`. Streamed through
  the app also with a bucket (a presigned redirect would be cached past its
  expiry; the file is a few kilobytes).
- **The mark** (`{% avatar person size %}`, sizes `sm`, `md`, `lg`;
  `frontend/avatar.js` for what scripts build): the image where the viewer
  may know the person (the tag checks, once per request, so no broken
  images), else white initials on the fill of one of the ten palette names,
  `PALETTE[id % 10]` (`data-avatar-color`, `User.avatar_color`). The
  contrast is the palette's "white on fill" check, and
  `AvatarColorsTest` that every name has its rule. `title` and `alt` are the
  full name.
- **Settings:** "Profile image" at the top of Appearance (upload, remove
  asking first). Admins remove other people's images on the person's page.
- **The person's page** (`/people/<id>/`, `organizations.people.person`):
  large mark, name, role, organization, the projects both are in
  (`Projects in common`), "Activity" (their feed, where the viewer may open
  it), "Remove image" for admins, "Change organization" as on the People
  page. The People page's names link here; the feed is one click further.
- **Places:** the People page, the person's page, comments, messages (page
  and board row), feed entries, the lantern's entries (who did it),
  assignee pills (server and picker), the `@` list, subscribers, the
  project's members (project page and people page), check-in answers and
  those asked, the live editor's others (their short name stays the
  label). Not in mails, and not in an item's history (staff only, names in
  text).
- **API and CLI** (CLI 0.26.0): `image_url` (absolute, or null) on every
  person, `PUT /api/v1/me/image/` (multipart, field `image`, 400 for a
  wrong file) and `DELETE`, both answer like `GET /api/v1/me/`;
  `biwak me image FILE` and `biwak me image --remove`. The multipart PUT
  needs ninja's `fix_request_files_middleware`.
- **The importer** (decided 2026-11-21): Basecamp's `avatar_url` is
  **not imported**. Its URLs (`.../people/<sgid>/avatar`, redirecting to the
  image) are the same for generated initials and uploaded images, so
  there's no marker to tell them apart without looking at a real account's
  answers, and the spec prefers our mark to a generated one. To change
  that: look at the redirect target and headers of a person with and without
  an uploaded image in a real account; `test_profile_images_are_not_imported`
  pins today's behavior.
