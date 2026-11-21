# Being offline: the connection banner

When the connection drops, people must know that what they do may not
arrive. Today only the live editor's status line says so; other pages
quietly stop updating, and a tick, a drag or a form sent offline ends on
the browser's error page.

**Status:** open (spec, 2026-11-21).

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
  merged when you're back." Plus "Don't close this tab until then",
  unless the typing is kept in the browser (see the question).
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

## Questions before building

1. **Keeping the live editor's typing in the browser** (Yjs's IndexedDB
   storage), so closing the tab, a crash or a restart while offline
   loses nothing; it is merged when the doc is opened again. Suggested:
   yes; then the banner doesn't need "Don't close this tab". The stored
   copy is removed once it's synced, and on logging out.
