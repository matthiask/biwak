# People: the mark, names and a page per person

How people are shown: a face or a colored mark makes lists, comments
and the lantern quicker to scan; names stay short but unambiguous. The
People page and organizations are `organizations.md`.

**Status:** stage 1 built (2026-11-21); stage 2 (drawn images) later.

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
- Without an image: white initials on the fill of a palette color
  chosen from the id (`PALETTE[id % 10]`, `User.avatar_color`), no
  setting. The full name is the `title` and `alt`.

## Profile images

- **Uploading** in the settings, "Profile image" at the top of
  Appearance: JPEG, PNG or WebP up to 5 MB, cut to the middle square,
  scaled to 256 pixels and stored as WebP (`operations.image_data()`,
  storage name `people/<id>/<version>.webp`, a random version per
  upload); "Remove" goes back to the initials. People set only their
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
person (`mail-sending.md`).

**Their recent activity** (decided 2026-11-22, replacing the person
feed page): their last 5 entries ("Recent activity"), rendered and
merged as the activity does with the person filter (`feed.preview()`,
`activity/_entries.html`), only what the viewer sees, then "All
activity" to `/feed/?person=<id>` (also in the palette). Only where the
activity's person filter takes them (people the viewer shares a project
with as members), and nothing at all when there are no entries.

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
  `/people/<own id>/name/` leads to the settings (fixed 2026-11-21 after
  a review, admins could rename themselves there). Also in the palette
  where the button is (added 2026-11-22).
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

## Stage 2 (later): choosing from drawn images

Instead of uploading, people pick one of a small set of drawn images
fitting Biwak's theme (a tent, a mountain, a lake, a fir, an ibex, a
marmot, …), each on a palette color, shipped with the app as SVG; choosing
stores its name. Waits for the drawings.
