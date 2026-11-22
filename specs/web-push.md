# Push notifications

Notifications on the phone (and the desktop) while Biwak isn't open,
through the browsers' Web Push. Asked by the user 2026-11-22: installed as
an app (`pwa.md`), Biwak tells people nothing there unless they read mail.

**Status:** being built (2026-11-22).

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
- **Only what came after subscribing** (proposed 2026-11-22): a
  notification pushes only for people with a device subscribed before
  it, so turning pushes on doesn't bring old mentions.
- **Failures:** a 404 or 410 deletes that device; when every device
  failed otherwise (logged), the notifications stay unpushed for the
  next run, until the `TTL` (12 hours) has passed (proposed 2026-11-22:
  the push service would drop it by then anyway).
- **The VAPID private key** may be the PEM or its lines between the
  markers joined into one (base64url DER or raw also work), for an
  environment variable.
