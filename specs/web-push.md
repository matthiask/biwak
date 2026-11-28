# Push notifications

Notifications on the phone (and the desktop) while Biwak isn't open,
through the browsers' Web Push. Asked by the user 2026-11-22: installed as
an app (`pwa.md`), Biwak tells people nothing there unless they read mail.

**Status:** built (2026-11-22); the test push built (2026-11-23).

## What pushes

- **Only what's for the person** (decided 2026-11-22: high priority
  only, a quiet phone): being mentioned and being assigned, the to-dos
  of one "Assign…" one push. Not the rest of what the lantern counts,
  not reactions, not what the person did themselves.
- **Quiet hours and out of office** (`quiet-hours.md`): no pushes outside
  working time or while away; nothing is sent later (the lantern has
  it).
- **Read in the lantern:** a push isn't sent for a notification already
  read. A push already shown stays when it's read elsewhere (decided
  2026-11-22: no silent push to close it, "let's not punish ourselves":
  Safari revokes subscriptions after a few pushes showing nothing,
  Chrome shows "This site has been updated in the background"); the
  `tag` per item replaces an item's older push.
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
- **Several devices per person** (decided 2026-11-22: people have a
  phone, a laptop, a desktop): each push goes to every device of the
  person; the list tells them apart by name, when added and when last
  used.
- **Devices have names** (decided 2026-11-23: two laptops with the same
  browser and system looked the same): by default the browser and system
  ("Firefox on Linux"); people rename their own devices ("Rename…" in the
  list).
- **A test push per device** (decided 2026-11-23 by the user: there was
  no way to check that pushes arrive): "Send a test" in the list, only
  for one's own devices, sends one push at once, whatever the quiet
  hours or being away (it's on purpose), and the page says whether it
  worked (below, "The test push").
- **One browser, one person** (decided 2026-11-22): a browser never has
  subscriptions for several people; the last one to subscribe on it
  replaces the other person's subscription there (nothing of before
  pushed). It never touches the same person's other devices.
- **Signing out ends pushes on that device** (decided 2026-11-22): an
  explicit sign-out removes the browser's device and says so on the
  next page ("Push notifications on this device are off."); a session
  that expires doesn't. Deactivating and "Reset sign-in…" remove all of
  the person's devices (decided 2026-11-28, `activation.md`,
  `two-factor.md`).
- **"Turn off on this device" on the push** (decided 2026-11-22: a
  browser signed out elsewhere, "Sign out everywhere else", keeps its
  pushes, and its settings are out of reach without signing in): a
  button on every push (`actions`, where browsers show them: Chrome,
  Edge, Android; not Safari or iPhones) ends the browser's subscription
  in the service worker, no sign-in needed; the next push to it fails
  with 410 and deletes the device. Otherwise: "Remove" in the list on
  any other device, or blocking notifications in the browser.

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
  Not on requests or in threads, except the test push (below).
- Audit log for the new table; API: list and delete one's own devices.
  **No CLI support** (decided 2026-11-22): no commands for the devices;
  changed 2026-11-23 with the test push: `biwak devices` lists them and
  `biwak devices test ID` sends one.

## Building it

In this order, each step with its tests:

1. **Model:** `PushSubscription` in `biwak/accounts/` (user, endpoint
   unique, `p256dh`, `auth`, user agent, `created_at`,
   `last_success_at`), `audit_tables()` in the migration
   (`biwak/audit/migrations/0002_audited_tables.py` shows how). A
   `Notification` gets `pushed_at` (null), like `sent_at`.
2. **Which notifications push:** a function `push.wanted(notification)`:
   the event's data names the person in `mentioned`, or the event is
   `Action.ASSIGNED` naming them in `assignees` (the same tests the
   lantern's "You were mentioned" and `mails.describe()` use; grep
   `"mentioned"` in `biwak/activity/`). Not read
   (`read_at`), not the person's own event.
3. **Sending:** `push.send_due(now)` called from `send_mails`
   (`biwak/activity/mails.py`, `send_mails()`; the command in
   `biwak/*/management/commands/send_mails.py` runs each part in its own
   `try`): notifications older than `mails.MERGE_AFTER` (10 minutes),
   not pushed, `wanted`, for people with subscriptions and not
   `quiet.mails_held(user, now)` (quiet hours, away:
   `biwak/accounts/quiet.py`); held ones are marked pushed without a
   push (nothing later). One push per item and person (several
   notifications of one item: the latest line), `pywebpush.webpush()`
   with the VAPID settings, `TTL` 12 hours; 404/410 delete the
   subscription, other errors are logged and left for the next run.
4. **Settings:** `WEBPUSH_VAPID_PUBLIC_KEY`, `WEBPUSH_VAPID_PRIVATE_KEY`,
   `WEBPUSH_SUBJECT` (`mailto:` the default from address) with speckenv
   in `biwak/settings.py`; empty: nothing offered or sent. How to make
   keys: `uvx --from py-vapid vapid --gen` (in the spec and
   `AGENTS.md`'s "Running it").
5. **Subscribing:** endpoints `POST`/`DELETE /accounts/push/` (session,
   CSRF; the JSON of `PushSubscription.toJSON()`), the settings'
   Notifications section: "Notify me on this device" (a button, then
   the browser's permission), the list of devices with "Remove",
   `frontend/push.js` loaded from `main.js`; the text for Safari on an
   iPhone not on the home screen ("Add Biwak to your home screen to get
   notifications on this iPhone."). API: `GET`/`DELETE
   /api/v1/me/push-subscriptions/` (own devices).
6. **Service worker** `frontend/sw.js` served at `/sw.js` (root scope,
   `Service-Worker-Allowed` not needed), only `push` (show the
   notification: title the lantern's line, body the project and the
   first line, `tag` the item's ID, `data.url`) and `notificationclick`
   (focus an open Biwak window on the URL or open one). No `fetch`
   handler: nothing cached.
7. **Translations** (`fl mm --language=de`), the help's notifications
   chapter (English and German), this spec's Status.



- Tests: what pushes and what doesn't (mentions and assignments only,
  own actions, read, quiet hours,
  away, clients' visibility), subscriptions deleted on 410, the setting
  only with keys; a browser test of subscribing (Chromium's push service
  can be stubbed).
- The help's notifications chapter says how.

## How it's built (2026-11-22)

- **Sending:** `biwak/activity/push.py`, `send_due()` from the
  `send_mails` command (its own `try`). `pending()` is `wanted()` in SQL
  (`to_jsonb(user_id)` against the event's `mentioned` and `assignees`),
  unpushed, not read and not marked unread in the lantern, grouped like
  the mails (`mails._groups()`: per person and item, the to-dos of one
  "Assign…" one push), each group once its newest is `MERGE_AFTER` old.
  What the person may see is `mails._deliverable()`, checked when
  pushing; what they mustn't see any more is marked pushed without a
  push.
- **Only what came after subscribing** (confirmed 2026-11-22): a
  notification pushes only for people with a device subscribed before
  it, so turning pushes on doesn't bring old mentions.
- **Failures:** a 404 or 410 deletes that device; when every device
  failed otherwise (logged), the notifications stay unpushed for the
  next run, until the `TTL` (12 hours) has passed (confirmed 2026-11-22:
  the push service would drop it by then anyway).
- **No locks while sending** (decided 2026-11-23, from a review): a
  group's notifications are claimed in a short transaction (`_claim()`:
  `select_for_update(skip_locked=True)`, `pushed_at` set), the push
  services are called outside it (up to `TIMEOUT` each), so marking
  them read in the lantern never waits; when every device failed, the
  claim is undone for the next run (within the `TTL`). A run dying
  between claiming and sending loses that push rather than pushing it
  twice.
- **The VAPID private key** may be the PEM or its lines between the
  markers joined into one (base64url DER or raw also work), for an
  environment variable.
  It's parsed once per run with something due (`_parsed_key()`); one
  that doesn't parse logs one error per run (no mail to the admins:
  other configuration errors only log or stop the start) and the run's
  pushes count as failed, so the `TTL` drops them instead of them
  piling up and all arriving late once the key is fixed (decided
  2026-11-23, from a review).
- **Subscribing:** `add_device()` and `remove_device()` in
  `biwak/accounts/operations.py`; `POST`/`DELETE /accounts/push/`
  (`push_subscription`, JSON, the CSRF token in `X-CSRFToken`, 204, 400
  for anything but a subscription with an `https` endpoint, 404 without
  the keys); "Remove" in the list posts to `/accounts/push/<id>/remove/`
  (works without JavaScript). One browser, one person (above): the
  endpoint is unique, a subscription of somebody else with this
  browser's endpoint is replaced; other endpoints, the person's other
  devices, are never touched.
- **Signing out:** subscribing sets a signed cookie with the device's ID
  (`biwak_push_device`, httponly, 400 days); `user_logged_out`
  (`biwak/accounts/signals.py`, `views.signed_out()`) removes the
  person's device of that cookie, and the one whose endpoint
  `frontend/push.js` adds to every sign-out form (`push_endpoint`; the
  page's `data-sign-out` names the URL) after unsubscribing the browser.
  Without JavaScript the cookie alone does it; the browser's own
  subscription then stays, unused. Only Django's `logout()` sends the
  signal, so expired sessions keep the device.
- **The settings' section** (`#devices`, only with the keys):
  `frontend/push.js` looks without registering anything; it shows the
  button, marks this device in the list ("This one", its "Remove" also
  unsubscribes the browser), says why there's no button (blocked, an
  iPhone outside the home screen) or that it failed. The texts are in
  the page. The list: the device's name (`PushSubscription.label`: the
  name, or the browser and system, `describe_agent()`, like the
  sessions), when added, when last used (the last push its push service
  took, "Never"). A device's actions ("Send a test", "Rename…",
  "Remove") are in a "…" menu at the end of its row, and phones leave
  out "Added" (decided 2026-11-23: three buttons were cramped on phones
  and scrolled the page sideways).
- **Names** (decided 2026-11-23): `PushSubscription.name`, empty for the
  browser and system (so a browser updating its user agent shows the new
  one). "Rename…" in the list opens the modal form
  `/accounts/push/<id>/rename/` (also a page; the browser and system as
  the field's placeholder, "Empty: the browser and system."), only for
  one's own devices (others' 404); `rename_device()` in
  `biwak/accounts/operations.py`. Spaces collapsed, at most 100
  characters (like teams' names), empty back to the default. The audit
  log has it (the trigger takes the whole row but the keys and
  `last_success_at`). Wording: the column "Device", "Rename…", the
  heading "Rename the device", the button "Rename" (German "Gerät",
  "Umbenennen…", "Gerät umbenennen").
- **The test push** (decided 2026-11-23 by the user): "Send a test" in
  the list (a button posting to `/accounts/push/<id>/test/`, like
  "Remove": works without JavaScript, no confirmation, nothing to fill
  in; no "…" since it opens nothing), only one's own devices (others'
  404), only with the keys. **Sent from the request** — an exception the
  user made to "nothing runs on requests" (`AGENTS.md`) and to pushes
  going out from `send_mails` only: a test must arrive at once and the
  page must say whether it worked. Only the test; everything else stays
  in `send_mails`. `push.send_test()` builds on `push.send()`, which
  sends one payload to one device (also what `deliver()` loops over),
  `TIMEOUT` as for every push, but a `TTL` of a minute (`TEST_TTL`,
  decided 2026-11-23: a late "it works" says nothing, an offline
  device shouldn't get it hours later). Content: title "Biwak", body
  "Push notifications work on this device." (German
  "Push-Benachrichtigungen funktionieren auf diesem Gerät."), `url` the
  settings' devices section, `tag` `biwak-test` (never replacing an
  item's push), the icon and the "Turn off on this device" button like
  every push, in the device owner's language. Ignores quiet hours and
  "away" (on purpose); a success updates `last_success_at` like a real
  push (not in the audit log). Said with a message on the settings after
  the redirect: "Sent. It should show up in a few seconds."; "That
  didn't work: the push service answered 500." (its status), "… the push
  couldn't be sent." (no answer), "… the server's push key is broken."
  (the private key doesn't parse); a 404 or 410 removes the device like
  a real push and says "This device's subscription had expired and was
  removed. Turn push notifications on again on it." No rate limit
  (decided 2026-11-23: it only reaches one's own devices). API: `POST
  /api/v1/me/push-subscriptions/{id}/test/` (write tokens; 404 for
  others' devices and without the keys) answers `sent`, `removed` and
  `detail` (the message), 200 whatever the push service said. CLI:
  `biwak devices` (the list), `biwak devices test ID` (exits 1 when it
  wasn't sent), `biwak devices delete ID` (the API's `DELETE`, decided
  2026-11-23), in `cli/biwak_cli/notifications.py`.
- **The service worker** is `frontend/sw.js` as it is, served by Django
  at `/sw.js` (public, `no-cache`), registered at the click. A push's
  JSON: `title`, `body`, `tag`, `url`, `icon` (`push.content()`); a tap
  focuses an open Biwak window and goes to the URL, or opens one.
- **Content** (confirmed 2026-11-22: the lantern's entry): title the
  item's title (a batch: "To-dos"), body the lantern's line with "You
  were mentioned." where the lantern says it, the lantern's excerpt (a
  comment's or message's text, about 200 characters) and the project;
  `tag` `biwak-item-<id>`.
- **Wording** (confirmed 2026-11-22): the heading "Push notifications",
  "When you're mentioned or assigned, also while Biwak isn't open; not
  in your quiet hours or while you're away.", "Notifications are blocked
  for Biwak in this browser's settings.", a failure "That didn't work.
  Please try again.", after signing out "Push notifications on this
  device are off." (German "Push-Benachrichtigungen", "Auf diesem
  Gerät benachrichtigen", "Füge Biwak zum Home-Bildschirm hinzu, …",
  "Push-Benachrichtigungen auf diesem Gerät sind aus.").
- **API:** `GET /api/v1/me/push-subscriptions/` (`id`, `name` (the
  list's: the given one or the browser and system), `device` (the
  browser and system), `user_agent`, `created_at`, `last_success_at`; no
  endpoint or keys; renaming only in the settings),
  `DELETE /api/v1/me/push-subscriptions/{id}/` (write tokens),
  `POST /api/v1/me/push-subscriptions/{id}/test/` (the test push).
- **Tests:** `biwak/activity/test_push.py` (what pushes, quiet hours,
  away, visibility, failures; `pywebpush.webpush` stubbed),
  `biwak/accounts/test_push_devices.py` (the section, subscribing,
  several devices, signing out, the test push, the API, the audit log),
  `biwak/test_cli_devices.py`, `biwak/test_e2e_push.py` (subscribing in
  Chromium with its `PushManager` stubbed; a push delivered to the
  worker through the DevTools protocol).
