# Installable as an app

The idea (2026-11-21): Biwak can be installed as an app (home screen,
dock), a progressive web app. Push notifications are postponed
(decided 2026-11-21, `lantern.md` already says "later").

**Status:** spec (2026-11-21). Not built.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`.

**Depends on:** nothing.

**Touches:** `base.html` (the manifest link, theme color, Apple's
icons), a view or a static file for the manifest, icons in
`biwak/static/biwak/`, `docs/orientation.md` (a sentence on
installing).

## What

- **A web app manifest** (`/manifest.webmanifest`): name "Biwak", short
  name "Biwak", `start_url` `/` (Home), `scope` `/`, `display`
  `standalone`, `background_color` and `theme_color` from the palette
  (the light theme's; `theme-color` meta tags with `media` for light and
  dark in `base.html`), icons 192 and 512 px (PNG, from the existing
  logo `biwak/static/biwak/favicon.svg`, plus a maskable variant with
  padding), served with the right content type.
- **Apple:** `apple-touch-icon` (180 px) and the
  `apple-mobile-web-app-*` meta tags, so "Add to Home Screen" on iOS
  gets the icon and a standalone window.
- **No service worker for now.** Chrome and Edge install without one;
  a service worker comes with push. **No offline caching:** cached
  pages would show stale data, and maybe what somebody may not see
  anymore (`access.md`). Offline, the existing connection banner says
  so (`connection.md`).
- **Inside the installed app:** links to other sites open in the
  browser (`target="_blank"` already for links in links); the top bar
  works without the browser's back button (the brand leads Home).
- The manifest is public (no login), it holds nothing secret; the
  icons too.

## Done when

- Chrome's and Edge's install prompt appear; Lighthouse's "installable"
  check passes (screenshot).
- iOS "Add to Home Screen" shows the icon and opens standalone
  (checked by the user on a phone).
- A Django test for the manifest's content and content type and the
  tags in `base.html`.
