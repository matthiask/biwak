# Sending mail through Resend, with an outbox

The idea (2026-11-21): move sending to Resend soon (the backlog's
"Sending through Resend" in `SPEC.md`), and with it queue outgoing mail
in the app, since the cluster's postfix (today's queue and retries) is
out of the way then.

**Status:** spec (2026-11-21), the questions answered the same day.
Not built.

**Agent:** a strong model: mail is easy to get subtly wrong (losing
mail, sending twice, codes arriving late).

**Depends on:** nothing; deploying it needs the From domain verified at
Resend (the user, in Resend's dashboard and the DNS).

**Touches:** `biwak/settings.py` (the mail backend), a new outbox (a
model in `biwak/activity/` or an app `biwak/outbox/`), `send_mails` and
`fairy_tasks`, the inbound webhook (`biwak/inbound/`, Resend's events),
`specs/notifications.md`, `docs/notifications.md`, the argocd values
(the user).

## Today

- Notification mails, digests and check-in mails are rows already
  (`Notification`, the check-ins' schedule), sent by `send_mails` every
  minute, retried on the next run when sending fails.
- Sent during the request: login codes (allauth), invitations (after the
  commit, `projects/operations.py`), the answer to a refused mail reply
  (`inbound/receive.py`), `mail_admins`. They go to postfix, which
  queues and retries; a failure to reach it answers 500 after the
  change was saved.
- From `biwak@feinheit.ch` through postfix and Gmail.

## Sending through Resend

- **Resend's HTTP API through `django-anymail`** (its Resend backend),
  not SMTP: the API answers with a message ID per mail, which the
  outbox stores, and Resend's webhooks report delivery, bounces and
  complaints by that ID. `EMAIL_URL` stays for development
  (`console:`) and tests (`locmem`).
- **From** `biwak@biwak.feinheit.app` (decided 2026-11-21), the
  domain verified at Resend, with
  the display name of the person acting where we have one, as today).
  `Reply-To` stays the reply address of `notifications.md` stage 2.
- **Tags** per kind of mail (`notification`, `digest`, `checkin`,
  `login-code`, `invitation`, `reply-refused`, `admin`) for Resend's
  dashboard.

## The outbox

Every outgoing mail goes through one table, so nothing is lost when
Resend is down and nothing is sent twice:

- **`OutgoingMail`:** the message (serialized: to, subject, text and
  HTML bodies, headers, attachments if any), its kind, `created_at`,
  `attempts`, `next_attempt_at`, `sent_at`, Resend's message ID, the
  last error, and the delivery state from the webhooks (delivered,
  bounced, complained).
- **Sending:** after the transaction commits, the mail is sent at once
  (one attempt, a short timeout); on failure it stays in the outbox and
  `send_mails` (every minute) retries with backoff (1, 2, 5, 10, 30
  minutes, then hourly), up to a limit (proposed: 24 hours), then gives
  up and tells the admins (`mail_admins` itself goes around the outbox,
  through the plain backend, so it can't loop).
- **No double sends:** a row is claimed (`select_for_update(skip_locked)`)
  before sending; an Idempotency-Key header (the row's ID) lets Resend
  drop a repeat after a timeout that actually went through.
- **Login codes** go through the outbox too, sent at once; a retry is
  pointless after the code's ten minutes, so they aren't retried after
  that (the person asks for a new one).
- **The notifications' own bookkeeping stays** (`sent_at`, merging, read
  ones left out); they hand their finished mail to the outbox instead
  of sending.
- **Only bookkeeping is kept** (decided 2026-11-21): once Resend has
  accepted a mail, its content (subject, bodies, attachments) is
  deleted from the row; recipient, kind, Resend's message ID, the
  attempts and the delivery state stay for the webhooks and debugging,
  30 days, then `fairy_tasks` deletes the row. The content is in
  Resend's own log if ever needed. Mails given up on keep their content
  until deleted with the row, for the admins to look at.

## Delivery events

- Resend's webhook (the existing `/inbound/resend/` with its secret,
  or a second endpoint) records `delivered`, `bounced`, `complained` on
  the outbox row.
- **A hard bounce or a complaint** (decided 2026-11-21) marks the address
  (`EmailAddress` or `User`: `mail_undeliverable_at`); no more
  notification mails and digests go to it, the person's page and the
  admin show it, signing in by code says the mail may not arrive. It
  clears when the person changes the address or an admin clears it.

## Done when

- Mail goes out through Resend in production, with the From domain's
  SPF, DKIM and DMARC passing (a test mail's headers looked at).
- Tests: sending at once after the commit, nothing sent on rollback, a
  failure retried with backoff, giving up after the limit and telling
  the admins, no double send with two `send_mails` running, login codes
  not retried after ten minutes, the webhook's events (signature
  checked), a bounce stopping notification mails, the cleanup after 30
  days.
- `notifications.md`, `SPEC.md` (the backlog item) and the help say so.
