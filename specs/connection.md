# Being offline: the connection banner

When the connection drops, people must know that what they do may not
arrive. Today only the live editor's status line says so; other pages
quietly stop updating, and a tick, a drag or a form sent offline ends on
the browser's error page.

**Status:** built (2026-11-21, branch `connection-banner`, not merged).
`frontend/connection.js` holds the state and the banner (`base.html`'s
`[data-connection]`); `live.js` and `collab.js` report their socket;
`http.js`' `send()` refuses while `navigator.onLine` is false and `post()`
takes an `undo` (`remember()`) for drags; the submit of forms is held back
with "Not sent". Decisions on the way: what the page does offline (undoing,
holding back, the `beforeunload` question) follows `navigator.onLine` only,
so a blocked websocket never keeps anyone from saving; the banner follows
the sockets too. htmx requests not made by a form (a button with
`hx-post`) aren't held back. Reactions are forms, so they are held back
with the message rather than undone. The editor's storage is
`frontend/collab-store.js` (`y-indexeddb`, database
`biwak-doc-<user>-<doc>-<history>`), cleared by `stored-docs.js` on
logging out. Clearing (decided 2026-11-21): while connected and synced the
editor asks the server (message 101, at most once a second per connection,
rate limited there) for its state vector as client clocks; the stored copy
goes once that covers the doc's own, and what it lacks is sent again, so
an update lost on the way keeps the copy. The guard: the page carries the
history of the server's `LiveState` (its `created_at`, `live.history()`);
copies of other histories of the same person and doc are deleted, never
merged (a recreated state would duplicate the text). Closing a tab online
doesn't start keeping the doc.
Tests: `biwak/test_connection.py`.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`.

**Depends on:** live updates and the live editor (`lantern.md`,
`collaboration.md`), `frontend/http.js`.

**Touches:**
- a small `frontend/connection.js` (the state and the banner);
- `live.js` and `collab.js` (reporting their socket's state);
- `http.js` (failed requests while offline);
- `base.html` (the banner's place);
- CSS.

## When

- **Offline** when the browser says so (`offline` event,
  `navigator.onLine`), or when the page's websocket (`/ws/live/` or the
  live editor's) has been disconnected for more than 3 seconds; short
  reconnects don't flicker.
- **Back** when the socket is connected again, or the browser is online
  and a request succeeds.

## The banner

A bar at the top of the page, under the navigation, in the warning
tone, with `role="status"` (`aria-live="polite"`). It never covers
content, and pushes it down instead.

- **In the live editor:** "You're offline. What you type is kept and
  merged when you're back." The typing is kept in the browser, so
  closing the tab is safe too (below).
- **On other pages:** "You're offline. This page isn't updating, and
  changes can't be saved until you're back."
- **Back:** "Back online." for 3 seconds. The page fetches what changed
  (as live updates already do), and the banner goes.

## What changes while offline

- **Ticks, drags, reactions** (`http.js` posts): they aren't sent. The
  change is undone in the page, with the banner explaining it. There's
  no reload to the browser's error page.
- **Forms:** submitting while offline is held back. The form keeps its
  text, and a message next to the button says "Not sent: you're
  offline." Nothing is queued and sent later automatically (no silent
  surprises).
- **Leaving a page with unsaved form input** while offline asks first
  (`beforeunload`).
- Without JavaScript nothing changes: the browser's own behaviour.

## Done when

Playwright tests (the browser set offline, as `test_offline_and_reconnect`
does):
- the banner after 3 seconds, not on a short blip;
- the editor's text and the other pages' text;
- a tick and a drag undone with the banner;
- a form held back with its text;
- "Back online." and the page catching up;
- screen readers: the status role.

## Keeping the live editor's typing (decided 2026-11-21)

The live editor keeps its unsent changes in the browser (Yjs's IndexedDB
storage), so closing the tab, a crash or a restart while offline loses
nothing: the changes are merged when the doc is opened again. The stored
copy is removed once the server has it, and on logging out.
