# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## The message board's order (`files.md`, 2026-11-22)

- On the board, staff see "Latest update" and "Newest posts" as two
  buttons that save the board's order for everybody at once; clients see
  the same two as `?order=` links (looking only). Staff look the other
  way without changing it only through `?order=` or the palette.
- The palette offers the other order as a link for everybody: "Newest
  posts first" or "Latest update first".
- Changing the order records no event and notifies nobody (like the
  files' order).
- The API's board is `GET`/`PATCH projects/{id}/message-board/`
  (`{"order": ...}`), messages carry `last_activity_at`.
