# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Filters on a list (2026-11-24, `todos.md`)

- The filter menu opened by hovering closes 300 ms after the mouse
  leaves it (50 ms to open was the user's), unless the select has the
  focus; a click on the button right after it opened keeps it open.
- A list's filter isn't remembered: a plain link to a list shows all of
  it (remembering per list would hide to-dos on the next visit).
- A to-do added inline while filtered shows even when it doesn't match;
  it's gone after the next reload.
