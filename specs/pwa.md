# Installable as an app

Biwak can be installed as an app (home screen, dock), a progressive web
app.

**Status:** built (2026-11-21).

- **The manifest** at `/manifest.webmanifest` (a view in `biwak/urls.py`,
  public: it holds nothing secret): "Biwak", `start_url` and `scope`
  `/`, `standalone`, icons 192 and 512 px and a maskable one
  (`biwak/static/biwak/`: the logo on the light stone `#eeebe4`, made
  once from `favicon.svg`). `theme_color` and the `theme-color` tags are
  the default accent's bar (`#5b37b0` light, `#3a2378` dark): the
  manifest is static, a person's accent isn't reflected.
- **Apple:** `apple-touch-icon` and the `apple-mobile-web-app-*` tags.
- **No service worker and no offline caching** (decided 2026-11-21):
  cached pages would show stale data, maybe what somebody may not see
  anymore. Offline, the connection banner says so (`connection.md`).
  Push notifications are postponed; a service worker comes with them.
- Links to other sites open in the browser (`target="_blank"`); the
  brand leads Home, so the app works without a back button.
