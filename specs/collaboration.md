# Real-time collaborative editing

**Status:** open, last (`SPEC.md`). **Agent:** a strong model.

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
- Server side either **`pycrdt` / `pycrdt-websocket`** (Yjs-compatible,
  Python) with Django Channels, or a small **Hocuspocus** (Node) service
  that only syncs and stores through the API. Decide with a spike; write
  the choice here.
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

A spike on the branch tries both (pycrdt-websocket with Channels inside
Django, and a small Hocuspocus service storing through the API) and
writes the choice here with what production needs (ASGI server, Redis
channel layer, a service, health checks, how websockets pass the
ingress). Nothing is deployed before the user has looked at it.

## Until then

Docs are locked while someone edits them (`files.md`).

## Done when

- Two and more people type in the same doc at once and see each other's
  text and cursors; nothing is lost.
- Offline edits merge on reconnect.
- `Doc.content` follows on a debounce; versions as snapshots; one event
  per editing session; search, mails, the API and agents see the
  Markdown.
- API edits during a live session arrive in the editors.
- Clients: live editing of their own docs, read-only watching of the
  others visible to them, nothing of internal docs (the websocket
  refuses them like the pages, 404); losing access closes the session.
- The locks of `files.md` replaced by live editing (or kept only where
  live editing isn't available), and the spec says which.

## Tests

Two and more clients editing concurrently (end-to-end, Playwright),
reconnecting after being offline, permission changes during a session,
API edits during a live session.

## No locks (decided 2026-11-21)

Docs are never locked again, also not if the live editor is ever turned
off: people get at most a heads-up that someone else is editing ("Ada is
editing this"), from the editing marker (`editor.md`).
