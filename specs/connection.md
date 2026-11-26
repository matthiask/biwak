# Being offline: the connection banner

When the connection drops, people must know that what they do may not
arrive, and nothing is lost silently.

**Status:** built (2026-11-21).

## When

`frontend/connection.js` keeps the state; `live.js` and `collab.js`
report their socket.

- **Offline** when the browser says so (`navigator.onLine`), or when
  the page's websocket (`/ws/live/` or the live editor's) has been
  disconnected for more than 3 seconds; short reconnects don't flicker.
- **Back** when the socket is connected again, or the browser is online
  and a request succeeds.
- **Dead connections** (decided 2026-11-21): the page pings `/ws/live/`
  every 30 seconds (and at once when it becomes visible or the browser
  comes online); without a pong within 10 seconds it replaces the socket
  and fetches what it missed (a laptop waking up, another network).
- What the page *does* offline follows `navigator.onLine` only, so a
  blocked websocket never keeps anyone from saving; the banner follows
  the sockets too.

## The banner and what changes

A box floating at the bottom of the window in the warning tone,
`role="status"` (`[data-connection]` in `base.html`), at the top of
the window while a selection bar takes the bottom (it has two rows on
phones); the page never moves (decided
2026-11-26 with the user: the bar under the navigation pushed the page
down, twice with "Back online."):

- in the live editor: "You're offline. What you type is kept and merged
  when you're back.";
- elsewhere: "You're offline. This page isn't updating, and changes
  can't be saved until you're back.";
- "Back online." for 3 seconds, and the page fetches what changed.

- **Ticks and drags** (`http.js`' `send()`, `post()` with an `undo`)
  aren't sent and are undone in the page.
- **Forms** (reactions included) are held back with their text and "Not
  sent: you're offline." Nothing is queued and sent later (no silent
  surprises). htmx requests not made by a form aren't held back.
- **Leaving** with unsaved form input while offline asks first.
- Without JavaScript, the browser's own behaviour.

## Keeping the live editor's typing

Decided 2026-11-21: the editor keeps unsent changes in IndexedDB
(`frontend/collab-store.js`, `y-indexeddb`, database
`biwak-doc-<user>-<doc>-<history>`), so closing the tab, a crash or a
restart while offline loses nothing.

- **Cleared** once the server has it: while synced the editor asks for
  the server's state vector (message 101, at most once a second, rate
  limited); the copy goes once that covers it, and what it lacks is sent
  again. Also cleared on logging out (`stored-docs.js`).
- **The guard:** the page carries the history of the server's
  `LiveState` (its `created_at`, `live.history()`); copies of another
  history are deleted, never merged (a recreated state would duplicate
  the text).
