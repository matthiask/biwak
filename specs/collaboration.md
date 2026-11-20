# Real-time collaborative editing

Several people writing in the same doc at the same time, above all for
meeting notes. No office suite. Built last and separately: it brings
websockets and ASGI into an otherwise plain Django app.

## Approach

Use an existing CRDT library, nothing homegrown:

- **Yjs** in the browser, with the editor's binding (ProseMirror/Tiptap or
  whichever editor `core.md` chose), cursors and names of the others
  (awareness), offline edits merged on reconnect.
- Server side either **`pycrdt` / `pycrdt-websocket`** (Yjs-compatible,
  Python) with Django Channels, or a small **Hocuspocus** (Node) service
  that only syncs and stores through the API. Decide with a spike; write
  the choice here.
- Store the Yjs state, and on a debounce the derived HTML and Markdown for
  search, mails, the API and agents. Agents edit through the API, which
  applies their change as a Yjs update.
- Versions as snapshots (`files.md`), not keystrokes; one event per
  editing session ("Ada edited the notes").
- Permissions as for any doc: whoever can see it can edit it, clients
  only if it's visible to them; a read-only option per doc.

## Until then

Docs are locked while someone edits them (`files.md`).

## Tests

Two and more clients editing concurrently (end-to-end, Playwright),
reconnecting after being offline, permission changes during a session,
API edits during a live session.
