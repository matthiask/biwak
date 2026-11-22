# People: the mark, names and a page per person

How people are shown: a face or a colored mark makes lists, comments
and the lantern quicker to scan; names stay short but unambiguous. The
People page and organizations are `organizations.md`.

**Status:** stage 1 built (2026-11-21); stage 2 (drawn marks) built
(2026-11-22).

## The mark

Decided 2026-11-21:

- `{% avatar person size %}` (`sm`, `md`, `lg`; `frontend/avatar.js` for
  what scripts build), everywhere a person is shown in a list or next to
  their words: the People page and the person's page, comments, messages,
  feed entries, the lantern, assignee pills and the picker, the `@` list,
  subscribers, members, check-in answers and those asked, the live
  editor's others, the "Me" menu (only the mark on phones). Not in mails
  (images there need public URLs and are often blocked) and not in an
  item's history.
- Without a photo: the person's drawn mark (below) in white on the fill
  of a palette color chosen from the id (`PALETTE[id % 10]`,
  `User.avatar_color`), no setting. No initials (decided 2026-11-22:
  they collide and say little to people who don't know the person).
  The full name is the `title` and `alt`.

## Profile images

- **Uploading** in the settings, "Profile image" at the top of
  Appearance: JPEG, PNG or WebP up to 5 MB, cut to the middle square,
  scaled to 256 pixels and stored as WebP (`operations.image_data()`,
  storage name `people/<id>/<version>.webp`, a random version per
  upload); "Remove" goes back to the person's drawn mark. People set only their
  own image; admins remove anyone's (an unfitting image) on the person's
  page, recorded in the audit log (`User` is audited).
- **Serving** through a view, never from the storage directly
  (`accounts.views.person_image`,
  `/accounts/people/<id>/image/<version>.webp`): visible exactly where
  the person's name is, to whoever `organizations.people.known_people()`
  lists (own staff everybody, clients the members of their projects,
  externals their projects' people), else 404, also for an old version.
  `Cache-Control: private, max-age=1 year, immutable`; streamed through
  the app also with a bucket (a presigned redirect would be cached past
  its expiry).
- **API and CLI:** `image_url` (or null) on every person; `PUT` (multipart,
  field `image`) and `DELETE /api/v1/me/image/`; `biwak me image FILE |
  --remove`.
- **Basecamp's images** are imported once, never overwriting one set in
  Biwak, and those Basecamp generated are skipped (`import-basecamp.md`,
  decided 2026-11-21).

## The person's page

`/people/<id>/` (`organizations.people.person`), for whoever may know
the person, else 404: the large mark, name, role, organization, the
projects both people are in, admins' "Remove image" and "Change
organization". The notice that mail to them bounces, for staff and the
person (`mail-sending.md`). No "All people" link at the bottom (decided
2026-11-22: the navigation has the People page).

**Their recent activity** (decided 2026-11-22): their last 5 entries ("Recent activity"), rendered and
merged as the activity does with the person filter (`feed.preview()`,
`activity/_entries.html`), only what the viewer sees, then "All
activity" to `/feed/?person=<id>` (also in the palette), for whoever
may open the page (one rule with the activity's person filter, decided
2026-11-22), and nothing at all when there are no entries.

**Names and marks link here** (decided 2026-11-21) wherever people are
listed (subscribers, a to-do's assignees, members, a team's members, an
organization's people) and in mentions, and (decided 2026-11-22) names
in the activity (actors and the people an event names), the timeline,
the history, comments, a message's and a version's author, when the
viewer may open it (`known_people()`), else plain text: `{% person_page
person %}` for lists (with the mark), `{% person_link %}` for a name
alone, both through `people.linked_name()`, quiet (`.wb-person-link`).
Names inside a link (rows, the lantern) and in mails stay text. Mentions
in mails and in the API's `*_html` aren't links (the text leaves the
site).

## Names

- **Changing a name** (decided 2026-11-21): one's own full and short name
  in the settings ("Name"); others' through "Edit the name…" on the
  person's page, with the split of `activation.md` (staff correct
  clients' names, admins everybody's), e.g. somebody who signed up as
  "NACHNAME VORNAME". The audit log has it. Not oneself there:
  `/people/<own id>/name/` leads to the settings. Also in the palette
  where the button is.
- Short names where people are listed (mentions, subscribers, assignees,
  reactions' "Who?", the lantern, pickers): `get_short_name()` (the short
  name if set, else the first word of the full name). The full name in
  every `title`.
- **The same first name** (decided 2026-11-21, several staff share one):
  where someone else the viewer may know has the same short name, it
  becomes "Moritz F." (the last name's first letter); if that still
  collides, everybody involved gets the full name. `display_names(viewer)`
  in `biwak/organizations/names.py`, computed once per viewer (a request's
  user, a mail's recipient) over `known_people()`, not stored; `{%
  short_name person %}` in templates. The `@` list writes the form unique
  for the one typing. Not for the API's and CLI's `short_name` (data),
  the live editor's labels (one for all who see it) or the audit log.

## Stage 2: drawn marks

Decided with the user 2026-11-22. **Status:** built (2026-11-22).

- **The drawings** (approved 2026-11-22): 35 in
  `biwak/static/biwak/marks/`, 23 alpine (tent, ibex, marmot, lantern,
  cable car, …) and 12 generic (fox, owl, cup, rocket, …);
  `preview.html` there shows them at 20, 32 and 96 px. One color: a
  shape in `currentColor`, a second tone by opacity only,
  `viewBox="0 0 64 64"`, the motif inside a centered circle of radius
  24, readable at 20 px (no lines under 4 units). New ones follow the
  same rules.
- **Everybody has a mark**, stored (`User.mark`, the file's name), given
  when the account is created: the mark fewest active people of the
  same organization have (ties: the first in the list's order), so a
  team of up to 35 has no repeats. Imported people get one the same way;
  people who left keep theirs. The color stays the id's: a repeated
  mark usually differs in color.
  Confirmed by the user 2026-11-22: `User.save()` gives it to
  every new account without one (sign-up, invitation, the importer, the
  admin), `marks.mark_for()`; the list's order is `marks.MARKS` (the
  preview's: the alpine ones, then the generic ones), people without
  an organization count among each other. "Active" counts everybody
  who hasn't left (`left_at`), also those waiting to be activated: an
  import's people are inactive until then and would otherwise all get
  the first mark. A changed organization keeps the mark. A data
  migration gave everybody there a mark in the order of their ids.
- **No initials:** the mark is shown wherever there's no photo. The full
  name stays the `title` and `alt`.
- **No color choice** (decided 2026-11-22: deriving it from the accent
  color would give everybody the default's).
- **The settings,** "Profile image" at the top of Appearance: **Drawn**,
  the grid of all marks with one's own selected, a click chooses
  (saved at once, like the other choices there); **Photo**, uploading
  as now. A photo is shown instead of the mark; "Remove" brings the mark
  back. Confirmed by the user 2026-11-22: each drawing is a submit button
  (`settings_mark`, `/accounts/settings/mark/`, no script), on the
  person's own color, the chosen one ringed (`aria-pressed`), named
  for screen readers (`MARKS`' names, translated); saving says "Your
  mark has been saved." and comes back to the section. German: the
  drawn mark is "Zeichnung", "Drawn"/"Photo" "Gezeichnet"/"Foto".
- **Drawing:** like the icons (`frontend/styles/icons.css`), white
  through a CSS mask on the circle, one class per mark
  (`wb-mark-ibex`), so `{% avatar %}`, `frontend/avatar.js` (the live
  editor's others included) and the page's colors need nothing else.
  A test checks that every file has its class and every class its file
  (like `biwak/test_icons.py`). Built: `frontend/styles/marks.css`, the
  class sets the drawing (`--wb-mark-image`), `.wb-mark::before` masks
  `currentColor` with it; the bundle inlines the small drawings.
  `avatar_data` has `mark` instead of `initials`.
- **API and CLI:** `mark` on people (read), changing one's own mark in
  the settings endpoint; the CLI shows nothing new. Built: `mark` on
  every person, `PUT /api/v1/me/` takes `mark` (one of the names, else
  422); `biwak me image --remove`'s help says "Back to the drawn mark."
- **Done when:** tests for giving marks (fewest used, per organization,
  the importer), the settings as staff and client, the avatar's markup
  with and without a photo, the mark classes; the help's settings
  chapter says how.
