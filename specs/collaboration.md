# Real-time collaborative editing

Several people writing in the same doc at the same time, above all for
meeting notes. No office suite.

**Status:** built (2026-11-20), deployed: `biwak/collab/` (the
websocket, the shared state), `asgi.py`, the doc operations in
`biwak/files/operations.py`, `files/doc_live.html`, `frontend/collab.js`.

## Approach

- **Yjs** in the browser, bound to CodeMirror 6 (`y-codemirror.next`):
  docs are Markdown (decided 2026-11-20), so the shared document is the
  Markdown text itself (`content`). Cursors and names of the others,
  offline edits merged on reconnect.
- **Server side: Channels with `pycrdt` and our own consumer** (decided
  2026-11-20 after a spike against Hocuspocus and pycrdt-websocket's
  `YjsConsumer`, which keeps a Y document per connection). The reasons:
  the access checks are the app's own (`visible_to()`, `can_change()`)
  in the same process; storing goes through the operations with the
  authors of what was typed (events, versions, mentions, search work as
  for any edit); API edits and closing sessions are a message on the
  channel layer; one codebase and image, no Node service. The consumer
  speaks y-websocket's protocol.
- **No locks** (decided 2026-11-21): docs are never locked, also not if
  the live editor were ever turned off; at most a heads-up that someone
  else is editing (`editor.md`). What remains is the refusal of a
  whole-text save over somebody else's newer version (`base_version`,
  409 in the API; the CLI sends it) and the read-only option.

## Who

`live.access()`, as for any doc (decided 2026-11-20, after the
visibility review): staff edit what they see; clients edit docs they
created and watch the others they can see, read-only (text and cursors
update, they can't type); nobody edits a read-only doc. Internal docs,
other projects, trashed docs and no login: the websocket closes with
4404 (like a 404; the editor doesn't reconnect).

Access is checked again: after joining the channel groups, before
answering every sync, when an event may change it (moved, visibility,
trashed, archived, project edited, member removed), when a person or
project is saved, when the read-only option changes, when the person
logs out or out everywhere (that login session's websockets close at
once), every 60 seconds, and before passing on others' updates when the
last check is older than 5 seconds (so losing access doesn't depend on
one channel message, which Redis may evict). Not before every update: a
few queries per keystroke of everybody. Losing access closes the session
("You can't see this doc anymore.", the text removed); losing only the
right to type switches to watching.

Everybody connected to a doc is shown to everybody else there, clients
included, members or not: like the authors of comments, people acting in
a place clients see are shown to them (decided 2026-11-20). Names and
colors come from the server; each editor's awareness goes out under an
ID the server gives the connection, only the cursor, so nobody passes
for or removes somebody else.

## How it works

- **State** (`biwak/collab/models.py`, `live.py`): `LiveState` the Yjs
  document as of the last save, `LiveUpdate` every update since, stored
  as it arrives (nothing typed is lost when a process dies). Not
  audited (a row per keystroke); `Doc.content` is. Any number of
  processes serve a doc: the state lives in the database.
- **The websocket** (`/ws/docs/<id>`, `consumers.DocConsumer`): updates
  from editors are stored and passed to the others through the channel
  layer, those from watchers dropped; syncing answers from the stored
  state. Broken messages are logged and ignored.
- **Limits per connection** (to be tuned after real use): awareness 20
  at once then 10 a second, asking for awareness 2 then one per 10
  seconds, syncing 3 then one per 10 seconds; awareness up to 4 KB, the
  cursor's JSON 1 KB, a state vector 16 KB. Typing isn't limited, and
  nothing beyond the websocket frame limit limits a doc's size.
- **Storing** (`files.operations.save_live()`): 3 seconds after the last
  update, at least every 30 seconds while somebody types, and when an
  editor leaves; `fairy_tasks` saves what's left. It writes
  `Doc.content` through the doc operations: an `edited` event per
  person whose updates it merges (one per editing session of 10
  minutes), mentions credited to who typed them, a version by the rules
  of `files.md` (with several authors kept by whoever started it within
  its 10 minutes). What people typed who can't change the doc anymore is
  dropped unless others' updates build on it; then it stays without
  credit (decided 2026-11-20).
- **Edits from elsewhere** (the API, the CLI, restoring a version, a
  tick): applied as a minimal diff to the stored state (a three-way
  merge by Yjs, so unsaved typing stays), sent to the open editors after
  the commit, saved at once.
- **Line breaks are LF only** (`biwak/text.py`): CodeMirror counts CR LF
  as one character, Yjs as two, and edits landed off.
- **The page:** "Edit" opens the editor (`/docs/<id>/edit/`), "Watch
  live" for who can't edit. A status line (connecting, saved as you
  type, offline, watching, gone), who else is here, "Save as a
  version", attaching files. Read-only until the first sync. The title
  is the text's first line (`files.md`, "Docs"). Without JavaScript the
  page shows the text. Typing `@` doesn't complete names in the editor
  yet (the syntax works).
- **Read-only** (`Doc.read_only`, staff on the page, `read_only` in
  `PATCH /api/v1/docs/{id}/`, `biwak doc read-only DOC [--off]`): nobody
  edits, staff neither, until staff switch it off; no event; its
  checkboxes can't be ticked, comments still can.
- **Frontend:** `frontend/collab.js` is a chunk loaded on the editor
  page only (about 400 KB, fine): Yjs, y-websocket (cross-tab
  broadcasting off), CodeMirror with the Markdown language only, Yjs'
  undo, the toolbar of `editor.md`. Unsent typing is kept in IndexedDB
  (`connection.md`).

## Running it

- **Development:** `daphne` is in `INSTALLED_APPS` when `DEBUG`, so
  `runserver` serves the websockets; the rspack dev server passes
  `/ws/docs/` and `/ws/live/` on. Without `CACHE_URL` or `REDIS_URL` the
  channel layer is in memory, enough for one process.
- **Tests:** Channels' communicator (`biwak/collab/test_consumers.py`,
  transaction tests), `asgi.py` under uvicorn for the browser tests
  (`CollabTest` in `biwak/test_e2e.py`).
- **Production** (decided 2026-11-20: everything under ASGI, one
  deployment): the `Containerfile` runs granian (`--interface asginl`,
  4 workers: sync views run one at a time per worker under ASGI).
  The channel layer uses the Redis of `CACHE_URL` (decided 2026-11-21:
  same host, port and database, scheme `redis://`, no query string,
  `biwak/redis_url.py`; prefix `biwak`), `REDIS_URL` overrides it; one
  is required outside development and tests (an in-memory layer would
  keep editors on different workers apart), also for the cron jobs. The
  layer's Redis reads time out after 10 seconds, above the 5 it blocks
  waiting (redis-py's default of 5 closed every quiet websocket).
  `asgi.py` checks the `Origin` against `ALLOWED_HOSTS`. The ingress
  passes websockets on; stopping a pod makes editors reconnect and
  resync.
