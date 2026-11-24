# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Filters on a list (2026-11-24, `todos.md`)

- A list's filter isn't remembered: a plain link to a list shows all of
  it (remembering per list would hide to-dos on the next visit).
- A to-do added inline while filtered shows even when it doesn't match;
  it's gone after the next reload.
