# Push notifications

Notifications on the phone (and the desktop) while Biwak isn't open,
through the browsers' Web Push. Asked by the user 2026-11-22: installed as
an app (`pwa.md`), Biwak tells people nothing there unless they read mail.

**Status:** open.

## What pushes

- **Only what's for the person** (decided 2026-11-22: high priority
  only, a quiet phone): being mentioned and being assigned, the to-dos
  of one "Assign…" one push. Not the rest of what the lantern counts,
  not reactions, not what the person did themselves.
- **Quiet hours and out of office** (`quiet-hours.md`): no pushes outside
  working time or while away; nothing is sent later (the lantern has
  it).
- **Read in the lantern:** a push isn't sent for a notification already
  read; when it's read elsewhere, the shown push is closed on the
  devices that support it (`tag` per item, a `close` message).
- **Coalesced like mails** (decided 2026-11-22: Biwak isn't chat): a
  push waits the same merge window as the notification mail
  (`MERGE_AFTER`, `notifications.md`), so quick edits are one push.
- **Content:** the lantern's line ("Ada commented on Kick-off"), the
  project's name, the first line of the text for comments and messages;
  a tap opens the item. Clients only get what they may see (the
  notification already is).

## Choosing

- **Per device, opt-in:** the settings' Notifications section gets
  "Notify me on this device" (asks the browser's permission, then
  subscribes); the device appears in a list with "Remove". No prompt
  without a click.
- **Independent of mail:** mail delivery (each, digest, none) stays as
  it is; someone may want both, or only pushes (mail "none").

## How

- A small service worker (`frontend/sw.js`, served at `/sw.js`) that only
  shows pushes and opens their URL on a tap: still no caching of pages
  (decided 2026-11-21, `pwa.md`). On iPhones Web Push needs Biwak added
  to the home screen; the setting says so in Safari (fine, decided
  2026-11-22).
- No service of our own and no account anywhere: the browser's push
  service (Google's for Chrome, Mozilla's, Apple's) delivers what we send
  to the subscription's endpoint, encrypted end to end; VAPID is only a
  key pair we generate once to sign our requests. VAPID keys from settings (`WEBPUSH_VAPID_PUBLIC_KEY`,
  `WEBPUSH_VAPID_PRIVATE_KEY`, `WEBPUSH_SUBJECT`); without them the
  setting isn't offered. Sending with `pywebpush` from `send_mails`'
  run (every minute), through a `PushSubscription` (person, endpoint,
  keys, user agent, created, last success); a 404 or 410 deletes it.
  Not on requests or in threads.
- Audit log for the new table; API: list and delete one's own devices;
  the CLI doesn't push.

## Done when

- Tests: what pushes and what doesn't (mentions and assignments only,
  own actions, read, quiet hours,
  away, clients' visibility), subscriptions deleted on 410, the setting
  only with keys; a browser test of subscribing (Chromium's push service
  can be stubbed).
- The help's notifications chapter says how.
