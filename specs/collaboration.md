# Real-time collaborative editing

**Status:** built (2026-11-20, branch `collaboration`): `biwak/collab/`
(the websocket, the shared state, `asgi.py`), the doc operations in
`biwak/files/operations.py`, the editor page (`files/doc_live.html`,
`frontend/collab.js`), the read-only option (page, API, `biwak doc
read-only`, CLI 0.20.0: 0.19.0 on the branch, 0.20.0 after merging
main, whose 0.19.0 still took locks). Not deployed: production needs what "Running it"
says. Values the spec didn't fix are marked **?** below, built the way
described meanwhile. **Agent:** a strong model.

**Depends on:** everything (`files.md` stage 2 above all: docs,
versions).

Several people writing in the same doc at the same time, above all for
meeting notes. No office suite. Built last and separately: it brings
websockets and ASGI into an otherwise plain Django app.

## Approach

Use an existing CRDT library, nothing homegrown:

- **Yjs** in the browser, bound to a plain-text Markdown editor
  (CodeMirror 6 with `y-codemirror.next`): docs are Markdown
  (decided 2026-11-20), so the shared document is the Markdown text
  itself. Cursors and names of the others (awareness), offline edits
  merged on reconnect.
- Server side **`pycrdt`** (Yjs-compatible, Python) with Django Channels
  inside the app (decided 2026-11-20 by the spike, below).
- Store the Yjs state, and on a debounce the Markdown in `Doc.content`
  for search, mails, the API and agents. Agents edit through the API, which
  applies their change as a Yjs update.
- Versions as snapshots (`files.md`), not keystrokes; one event per
  editing session ("Ada edited the notes").
- Permissions as for any doc (decided 2026-11-20, after the visibility
  review): staff edit what they see; clients edit live only docs they
  created and watch the others they can see live, read-only (the text
  and others' cursors update, they can't type). A read-only option per
  doc. Losing access during a session closes it for that person.

## Deciding the server side (decided 2026-11-20)

A spike tried both, each with a page with CodeMirror and Yjs, two
browsers (Playwright) typing, a client watching, an internal doc
(commit "Collaboration spike" on the branch, removed afterwards):

- **Channels with pycrdt-websocket's `YjsConsumer`**: the browsers'
  y-websocket provider syncs with it, pycrdt reads and writes Yjs updates
  (also with text beyond ASCII), the check on connect is two lines with
  `Item.objects.visible_to()`. But the consumer keeps a Y document per
  connection: the doc's text was inserted once per connection, so two
  editors saw it twice, and nothing was stored. Usable are pycrdt's
  documents and sync messages, not the consumer.
- **Hocuspocus** (Node, `@hocuspocus/server` 4.9) asking Django whether
  the session may connect (forwarding the cookie), loading the Markdown
  and storing it through an endpoint with a service token: synced
  correctly at once, debounces storing on its own. But its store hook
  doesn't know who edited (tracked by hand for the spike), and everything
  else crosses the service boundary twice: API edits during a session
  need Django to call Hocuspocus (`openDirectConnection`), losing access
  needs Django to tell Hocuspocus to close connections, and more than one
  instance needs its Redis extension.

**The choice: Channels with pycrdt, our own consumer.** The reasons:

- The checks are the app's own: `Item.objects.visible_to()` and
  `can_change()` on connect and again whenever something may have taken
  access away, in the same process, no endpoint and no service token.
- Storing goes through the operations directly, with the authors of
  what was typed: events, versions, mentions, attachments and search work
  as for any other edit.
- API edits and closing sessions are a message on the channel layer;
  Hocuspocus needs calls from Django to Node for both.
- One codebase and one image: Python and the bundle, no Node service to
  build, deploy, monitor and update.
- The cost: about 300 lines of consumer and state handling instead of
  Hocuspocus' mature server, and Channels' ASGI next to WSGI. The
  consumer speaks y-websocket's protocol, so the browser side is the
  standard Yjs provider.

## How it works (built)

- **State** (`biwak/collab/models.py`, `live.py`): `LiveState` holds the
  doc's Yjs document as of the last save, `LiveUpdate` every update
  since, stored as it arrives (nothing typed is lost when a process
  dies). The state's text always equals `Doc.content` after a save; it's
  made from the content when a doc is first opened live, and follows the
  content when that changed some other way. Neither table is audited (a
  row per keystroke); `Doc.content` is. The Y document's text is named
  `content`.
- **The websocket** (`/ws/docs/<id>`, `consumers.DocConsumer`, y-websocket's
  protocol plus one message of ours saying whether the editor may type):
  updates from those who may edit are stored and passed to the doc's
  other editors through the channel layer, those from watchers dropped.
  Syncing (also after being offline) answers from the stored state and
  asks the editor for what it has that the server doesn't. Awareness is
  passed on with the name and color set by the server (nobody passes for
  somebody else), only the editor's own state; leaving tells the others.
  Everybody connected to the doc (who may see it) is shown to everybody
  else there, clients included, members of the project or not: like the
  authors of comments, people acting in a place clients see are shown to
  them (decided 2026-11-20, after the visibility review). Each editor's
  state goes out under an ID the server gives the connection and with
  only the cursor, so nobody changes or removes somebody else's.
  Broken messages are logged and ignored. Any number of processes can
  serve a doc, the state lives in the database.
- **Who** (`live.access()`): staff edit what they see, clients the docs
  they created and watch the others they see; nobody edits a read-only
  doc; internal docs, other projects, trashed docs and no login: the
  websocket accepts and closes with 4404 (like the pages' 404; the editor
  doesn't reconnect). Checked again right after joining the channel
  groups that tell about changes, before answering every sync, when an
  event may change access (moved, visibility changed, trashed, archived,
  project edited, member removed or left), when a person is saved
  (admin: deactivated, made a client) or a project (admin: made limited,
  archived), when the read-only option changes, when the person logs
  out or logs out everywhere (`user_logged_out` and usersessions'
  sessions deleted: the websockets of that login session close at once,
  fixed 2026-11-21 after the visibility review of the live features), and
  every 60 seconds (**?**), which also closes sessions whose login session
  is gone some other way. And before passing on others' updates and
  cursors when the last check is older than 5 seconds (**?**, added
  2026-11-21 after the visibility review of the live features): losing
  access doesn't depend on the one message telling the editors (Redis may
  evict it, a change in the database directly sends none). Not before
  every update: a few queries for every keystroke of everybody. Losing access closes the session (4404; the
  editor shows "You can't see this doc anymore." and removes the text);
  losing only the right to type switches the editor to watching.
- **Storing** (`files.operations.save_live()`): 3 seconds after the last
  update from an editor, at least every 30 seconds while somebody keeps
  typing, and when an editor leaves (**?** both). It merges the pending
  updates into the state and writes `Doc.content` through the doc
  operations: an `edited` event for each person whose updates it merges
  (merged into their event of the last 10 minutes: one per editing
  session), mentions, attachments, a version by the version rules of
  `files.md`. With several authors the newest version is updated when it
  is by one of them and younger than 10 minutes, else a new one is made
  by the first of them (**?**). Mentions newly typed are credited to who
  typed them (whose updates completed them), the others to the first
  author. What people typed who can't change the doc anymore when it's
  saved (no longer seeing it, a client now) is dropped; when others'
  updates build on it (Yjs would leave their text out too), it stays,
  but they're no authors: no event, no mentions (decided 2026-11-20,
  after the visibility review). Trashing and the read-only option don't
  drop what was typed before. `fairy_tasks` saves what is left (a
  process stopped while somebody typed).
- **Edits through the API, the CLI, restoring a version, renaming**
  (`update_doc()`, `restore_doc_version()`): the new content is applied
  as an edit (a minimal diff) of the stored state, whose text is the
  content the API returned last, so what people typed meanwhile and
  isn't saved yet stays (a three-way merge by Yjs); the update goes to the
  open editors after the commit, and the doc is saved at once. A client
  that read the content before somebody else's save overwrites that save
  unless it sends `base_version` (409 then), as before; the CLI does.
- **The page**: "Edit" on a doc opens the editor (`/docs/<id>/edit/`);
  who can't edit it gets "Watch live" and the same page read-only. Above
  the editor its state ("Connecting…", "Changes are saved as you
  type.", "Offline. Your changes are kept and merged when the connection
  is back.", "You are watching. You can't change this doc.", "You can't
  see this doc anymore.", **?** wording) and who else is here; below it,
  for editors, attaching files (dropping, pasting, the button) and a form
  to rename the doc and "Save as a version". The editor is read-only
  until the first sync (typing before it would land before the text).
  The title isn't edited live.
- **Read-only option** (`Doc.read_only`, `set_read_only()`): staff switch
  it on the doc's page, in the API (`read_only` in `PATCH
  /api/v1/docs/{id}/`) and with `biwak doc read-only DOC [--off]`. Nobody
  edits a read-only doc, staff neither (pages, editor, API, restoring;
  409 in the API) until staff make it editable again (**?**). No event.
- **The locks of `files.md` are gone** (`Doc.locked_by`, `locked_at`,
  `/docs/<id>/lock/`, `frontend/doc-lock.js`, the API's lock endpoints
  and `locked_by`): live editing works wherever the doc page works.
  What remains of them is the refusal of a whole-text save over somebody
  else's newer version (`base_version`, API and CLI), and the read-only
  option for docs that mustn't change. Without JavaScript the editor page
  shows the text only. CLI 0.20.0 doesn't take locks anymore; older CLIs
  are refused (`MINIMUM`).
- **Frontend**: `frontend/collab.js`, a chunk loaded on the editor page
  only: Yjs, y-websocket (cross-tab broadcasting off: every tab goes
  through the server), CodeMirror 6 with the Markdown language only (not
  `markdown()`, which brings HTML, CSS and JavaScript), Yjs' undo. The
  chunk is about 400 KB minified (**?** acceptable). Typing `@` doesn't
  complete names in the editor yet (`mentions.js` works on text fields;
  the syntax works).

## Running it

- **Development**: `fl dev` as before. `daphne` (a development
  dependency) is in `INSTALLED_APPS` when `DEBUG`, so `runserver` serves
  the websockets; the rspack dev server passes `/ws/docs/` on to it
  (`rspack.config.js`, its own websocket is `/ws`). Without `CACHE_URL`
  or `REDIS_URL` the channel layer is in memory, enough for one process.
- **Tests**: `./runtests.sh` needs nothing new. The websocket tests use
  Channels' communicator (`biwak/collab/test_consumers.py`, transaction
  tests: the consumer commits), the end-to-end tests run `asgi.py` with
  uvicorn (a development dependency) in the live server's thread
  (`CollabTest` in `biwak/test_e2e.py`).
- **Production** (decided 2026-11-20: everything under ASGI, one
  deployment):
  - **The image runs ASGI**: the `Containerfile` starts `granian
    --interface asginl asgi:application --workers 4`, for pages and
    websockets alike (sync views run one at a time per worker under
    ASGI, hence four workers instead of two). The chart stays as it is.
  - **Redis** for the channel layer: the shared Redis of `CACHE_URL`,
    which the cluster sets already (e.g.
    `hiredis://redis:6379/1/?key_prefix=…`; decided 2026-11-21, no
    separate `REDIS_URL`): the same host, port and database, the scheme
    `redis://`, without the query string (`biwak/redis_url.py`); the
    channel layer's own prefix `biwak` keeps its keys apart from the
    cache's. `REDIS_URL` overrides it when set. One of them is required
    outside development and tests (the app refuses to start without:
    an in-memory layer would keep editors on different workers apart), in
    the environment of the deployment and the cron jobs (`fairy_tasks`
    sends access checks to the editors). The image's build environment
    (`conf/_env`) has a placeholder `CACHE_URL`. The shared Redis evicts
    with `allkeys-lru` at 200 MB; channel messages live seconds, so
    eviction would only drop a message under memory pressure (the editors
    resync on reconnect).
  - **Websockets through the ingress**: HAProxy ingress passes
    websockets on without configuration; its tunnel timeout (1 hour by
    default) is far above the editors' 15-second awareness heartbeat. The
    session cookie authenticates; `asgi.py` checks the `Origin` against
    `ALLOWED_HOSTS`.
  - **Health checks**: the ASGI process serves HTTP too (to Django), so
    the deployment's HTTP probe works as it is (`httpprobe: /`).
  - **Cron**: nothing new; `fairy_tasks` saves what's left over.
  - **Stopping a pod**: editors reconnect to another process and resync;
    what was typed is stored already, it's saved by the next editor's
    save or by `fairy_tasks`.

## Done when

- Two and more people type in the same doc at once and see each other's
  text and cursors; nothing is lost. **Done**: `CollabTest` (three
  browsers), `test_consumers.py`.
- Offline edits merge on reconnect. **Done.**
- `Doc.content` follows on a debounce; versions as snapshots; one event
  per editing session; search, mails, the API and agents see the
  Markdown. **Done**: `test_live.py`.
- API edits during a live session arrive in the editors. **Done.**
- Clients: live editing of their own docs, read-only watching of the
  others visible to them, nothing of internal docs (the websocket
  refuses them like the pages, 404); losing access closes the session.
  **Done.**
- The locks of `files.md` replaced by live editing (or kept only where
  live editing isn't available), and the spec says which. **Done**: no
  locks are left, see above.

## Tests

Two and more clients editing concurrently (end-to-end, Playwright),
reconnecting after being offline, permission changes during a session,
API edits during a live session: `biwak/collab/test_consumers.py`,
`test_live.py`, `CollabTest` in `biwak/test_e2e.py` (six browser tests,
about 20 seconds).

## Decided after building (2026-11-20)

- Saving 3 seconds after the last keystroke, at least every 30 seconds,
  checking access every 60 seconds.
- The read-only option: nobody edits, staff neither, until staff turn it
  off; no event, no notification.
- The editor's chunk (about 400 KB) is fine; `MINIMUM` 0.20.0 for the CLI
  is fine (no CLI users yet).

## Confirmed 2026-11-21

- The wording of the editor's states and of "Watch live", "Make
  read-only", "Make editable" (to be reviewed with the German
  translation).
- Versions with several authors: kept by whoever started the version
  within its 10 minutes.
- No limit on the size of an update or a doc beyond the server's
  websocket frame limit.

## Questions (built the way described meanwhile)

- The limits per connection (added 2026-11-21 after the visibility review
  of the live features, `consumers.py`): awareness 20 messages at once,
  then 10 a second; asking for the others' awareness 2, then one every 10
  seconds; syncing (which loads the whole doc) 3, then one every 10
  seconds; awareness messages up to 4 KB, the cursor's JSON up to 1 KB,
  a sync's state vector up to 16 KB. More is dropped and logged once per
  connection. Typing isn't limited.

## No locks (decided 2026-11-21)

Docs are never locked again, also not if the live editor is ever turned
off: people get at most a heads-up that someone else is editing ("Ada is
editing this"), from the editing marker (`editor.md`).
