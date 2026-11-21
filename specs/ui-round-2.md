# UI round 2

The second round of feedback from using Biwak (`ui-feedback.md`, added
2026-11-21), plus two follow-ups from the same day: mentions by first name,
and Basecamp's profile images. Three parts that touch different files, so
they can be built in parallel.

**Status:** open (spec, 2026-11-21).

**Agent:** cheaper models; each part follows the checklist in `AGENTS.md`.

**Depends on:** `lantern.md`, `people.md` stage 1 and `ui-round-1.md`,
all merged.

## Part A: the lantern

**Touches:**
- `biwak/templates/activity/_lantern_menu.html`, `_lantern_groups.html`,
  `lantern.html`;
- `biwak/activity/lantern.py`, `views.py` (the count), `api.py`;
- `frontend/lantern.js`;
- CSS.

1. **Read and unread are told apart at a glance.** Today only bold text
   marks unread entries.
   - An item with unread notifications gets a small dot before its
     title, in the same red as the lantern's dot (`--wb-lantern-dot`).
   - Read items are quieter: the title and lines in the secondary text
     color, not bold.
   - "Read" and "Unread" headings aren't needed: the groups are already
     ordered unread first.
   - The same on the lantern's page.
2. **Wider:** the menu is `min(34rem, 100vw - 2rem)` wide (now 26rem),
   so lines and excerpts wrap less. Keep it on the screen (`menus.js`
   places it).
3. **The count is the number of entries, not notifications.** The menu
   groups notifications by item, so "7 unread" with 5 entries confuses.
   - The count, its tooltip and screen-reader text count items with
     unread notifications (`unread_count()`).
   - The API's `GET /api/v1/lantern/` keeps `unread` as the number of
     notifications and adds `unread_items`. `biwak lantern` prints the
     items, as the menu does.
   - The mails' digests are unaffected.
4. **One divider between bookmarked, unread and read groups.** Today two
   lines show between unread and read: the last unread item's border plus
   the `<hr>`. Drop the `<hr>` where a group's border already separates
   them, or the last border before an `<hr>`.

**Status (part A):** built (2026-11-21, CLI 0.27.0). Unread items have the
red dot (`.wb-lantern-unread`), read ones are quiet (secondary color, not
bold) in the menu and on the page; the menu is 34rem wide; the count,
its tooltip and `/lantern/count/` count items (`lantern.unread_count()`,
`unread_counts()` gives both numbers); the `<hr>`s are gone, the items'
borders separate the groups. Decided on the way: the API's list had no
`unread` before, so it now answers `unread` (notifications) and
`unread_items` next to `results`, `biwak lantern` prints one row per item
("(+N)" for more entries; `--json` stays the entries).

**Done when:**
- Django tests for the count by items (several notifications on one
  item count once), the API's two numbers, and the markup of read and
  unread items.
- A browser test: the dot on unread items, a read item quiet, one
  divider.
- A screenshot of the open menu, light and dark, in the report.

## Part B: people in the interface

**Touches:**
- `biwak/templates/base.html` (the "Me" menu);
- `biwak/templates/items/_todo_view.html` and the CSS of `.wb-facts`;
- `biwak/activity/mentions.py` and `frontend/mentions.js`.

1. **The "Me" menu shows the person's mark** (`{% avatar request.user
   "sm" %}`, `people.md`) before or instead of the name: the image or the
   colored initials. The name stays for screen readers and in the
   menu's first line. On phones only the mark.
2. **The facts line on to-dos aligns.** `.wb-facts` (assignees, due date,
   repeat) isn't vertically aligned. The labels, values, avatars in pills
   and badges should sit on one center line, and wrapping keeps each fact
   together.
3. **Mentions show the first name.**
   - Mentions are shown as "@Ada", not "@Ada Example". That's the
     person's short name (`get_short_name()`: the short name if set, else
     the first word of the full name).
   - The full name is in the mention's `title`.
   - Rendering uses the person's current short name, so renaming someone
     updates old mentions.
   - Where the reader may not know the person, the text stays as written
     (`mentions.py` already falls back).
   - The `@` list inserts `[@Ada](person:ID)`. Stored texts keep working,
     since the label is only a fallback.
   - The same in mails and in the plain-text excerpts (the lantern, the
     feed).

4. **Names and marks link to the person's page** (decided 2026-11-21).
   Wherever a person's mark and name are listed (subscribers, the assignee
   pills of a to-do in view mode, the members on the project and its
   people page) and in mentions, they link to `/people/<id>/` when the
   viewer may open it (`known_people()`, the page's own rule), else stay
   plain text. `{% person_page person %}` is the one place for lists; the
   link is quiet (`.wb-person-link`: no underline until hover). Mentions
   in mails and in the API's `*_html` are not links (the text leaves the
   site). Assignee pills have a `gap` of 0.25rem in the facts line.

**Done when:**
- Tests for rendering old and new mentions, a renamed person, a mention
  of someone the reader doesn't know, and mails and excerpts.
- A browser test inserting a mention through the `@` list.
- The "Me" menu with an image and with initials.
- A screenshot of the facts line in the report.

**Status:** part B built (2026-11-21): the "Me" menu with the mark (and
the full name as its first line), the aligned facts line, mentions by
short name (`mentions.visible_people()`; `syntax()` and the `@` list write
the short name as the label), and `{% person_page %}` links. Mentions in
mails keep the plain look. Decided on the way: `syntax()` (the API's and
mail replies' `@Name` resolution) writes the short name as label too.

## Part C: Basecamp's profile images

**Touches:** `biwak/importer/` only.

`people.md` left Basecamp's images out because generated initials and
uploaded photos look the same in the API. Checked against a real account
on 2026-11-21 (read-only, 104 people):
- **Same API shape for both:** every person's `avatar_url` answers 200
  with the same kind of headers, whether it's a photo or generated.
- **The URL:** `people.json` lists `avatar_url` as null. Only
  `people/<id>.json` has it.
- **Generated images** are a flat colored square with white initials, or
  Basecamp's beige placeholder. They can be told apart by their content.
  Scaled to 64 pixels:
  - the four corners have the same color (a difference under 12 per
    channel);
  - quantized to 8 colors, the most common one covers at least 60% of
    the pixels.

  68 of 104 were generated, and all of them passed this test. The three
  closest real images (a drawing, an illustration, a dark photo) failed
  it, as they should.

What to build:
- **When:** importing a person whose Biwak account has no image yet,
  fetch the image once (`Accept: image/png, image/webp`) and keep it,
  unless it looks generated by the rule above. Never overwrite an image
  set in Biwak.
- **How:** through the same processing as an upload (square, 256 px,
  WebP), in `importing()` so nothing is notified.
- **The report** lists images imported and skipped as generated.
- **A dry run** fetches nothing.

**Done when:** tests with made-up images (a flat square with letters, a
noisy "photo", a flat-cornered image with lots of detail) and a faked
download. A second run doesn't fetch again for people who have an image.
No requests to the real Basecamp from the tests.

**Status (built 2026-11-21):** `biwak/importer/images.py`
(`looks_generated()`, the numbers above, scaled with Lanczos),
`Importer._image()` called for each person of a project after the person
is found or created: skipped in a dry run and for people with an image
(no request at all), else `people/<id>.json` for the `avatar_url`, then
`client.download(url, accept="image/png, image/webp")` and
`accounts.operations.store_image()` (the upload's processing without the
permission check), inside the run's `importing()`. Failures (404, not an
image) are report problems. The report lists "Profile images imported" and
"skipped, generated by Basecamp". Generated images leave the person
without one, so a later run looks at them again (one request each); people
with an image are never fetched again. Tests: `test_images.py` and the
profile image tests in `test_importer.py`, with images made by Pillow in
`support.py`.
