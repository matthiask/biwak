# Sending mail through Resend, with an outbox

Outgoing mail is queued in the app and sent through Resend's API, so
nothing is lost when Resend is down and nothing is sent twice. Replies
coming in are `notifications.md`.

**Status:** built and live in production (2026-11-21).

## The outbox

- **Explicit, not Django's default mailer:** the app's mails call
  `outbox.send(message, kind)` (`biwak/outbox/sending.py`) instead of
  `message.send()`; allauth's go through the account adapter's
  `send_mail()`. The default mailer (`EMAIL_URL`) is the transport the
  outbox sends with, so `mail_admins` and Django's error mails go around
  the outbox (they can't loop), and tests keep the locmem mailer.
- **`OutgoingMail`:** the serialized message, its kind, attempts, next
  attempt, sent, Resend's message ID, the last error, the delivery
  state. Not audited (only the system writes it); a read-only admin with
  a state filter (waiting, sent, given up).
- **Queued in the transaction of the change** (notifications and
  digests where they're marked sent, invitations, refused replies,
  login codes); check-in mails after the commit (they look at who sees
  the question then).
- **Sending:** at once after the commit (one attempt, 10 second
  timeout); a new row is due for `retry()` only a minute later, so the
  two don't race. `send_mails` retries with backoff (1, 2, 5, 10, 30
  minutes, then hourly, at most 200 a run); Resend's 429 isn't a failed
  attempt (the run stops, the row waits a minute).
- **No double sends:** `deliver()` locks the row
  (`select_for_update(skip_locked)`), and an `Idempotency-Key`
  (`<host>/outgoing-mail/<id>/<created>`: installations may share a
  Resend account, and a recreated database starts at the same IDs again,
  which Resend refuses for 24 hours when the body differs; the creation
  time added 2026-11-23 after that happened) makes Resend answer a repeat
  with the first mail's ID. Resend
  keeps keys 24 hours, **so nothing is tried after 24 hours**: such rows
  are given up. With other transports (SMTP) a crash between sending and
  our commit would send twice.
- **Giving up** tells the admins in one mail per run (kind,
  recipients, subject, attempts, last error, a link to the admin)
  through the plain mailer, and logs an error (Sentry). That notice goes
  through Resend too, so it may fail while Resend is down (accepted
  2026-11-21). Login codes past their ten minutes are given up quietly, the last error kept after "Not sent before the login code expired." (decided 2026-11-23: it was lost, and with it why the code never came).
- **Only bookkeeping is kept** (decided 2026-11-21): once the transport
  accepted a mail its content is deleted; recipients, kind, Resend's ID,
  attempts and delivery state stay. Mails given up keep their content.
  `fairy_tasks` deletes rows 90 days after they were queued (decided
  2026-11-24, 30 before; like incoming mails, `specs/auditing.md`).
- **Kinds** (Resend's tag `kind`): `notification`, `digest`, `stale` (stale to-dos,
  `stale-todos.md`), `checkin`,
  `login-code`, `invitation`, `reply-refused`, `account`, and `admin`
  for `mail_admins`.
- **From:** `DEFAULT_FROM_EMAIL`, with the acting person's name where
  there is one (invitations "Ada Example (Biwak)"), else "Biwak".

## Bounces and complaints

- Resend's events come to the existing `/inbound/resend/` (the same
  `RESEND_WEBHOOK_SECRET`, `biwak/outbox/events.py`): `email.delivered`,
  `email.bounced`, `email.complained`, matched by Resend's ID. The row
  keeps the worst state so far (delivered < bounced < complained).
- **A complaint or a `Permanent` bounce** (decided 2026-11-21) sets
  `User.mail_undeliverable_at` on the recipients (not allauth's
  `EmailAddress`: a person has one address, and the queries choosing who
  gets mail are on `User`); a temporary bounce is only noted on the row.
- **What it stops:** notification mails, digests and check-in
  mails.
  Their notifications stay in the lantern and are dropped (marked sent)
  when the mark clears. Login codes, invitations and answers to refused
  replies still go out: someone asked for them.
- **Clearing:** when `User.email` changes, by the admin, or the admin
  action "Mail to the selected people works again".
- **Shown** on the person's page (staff and the person), their
  settings page and the admin. **Not on the login page** (decided
  2026-11-21): it would tell whoever types an address that it has an
  account.

## Setting it up

1. Resend: the sending domain verified (SPF, DKIM, the bounce MX), a
   DMARC record (`p=none` to start).
2. Resend's webhook to `https://<host>/inbound/resend/` with the events
   `email.delivered`, `email.bounced`, `email.complained` (one secret for
   replies and events).
3. Environment: `EMAIL_URL=resend:` (not switched on by
   `RESEND_API_KEY` alone, which replies use), `DEFAULT_FROM_EMAIL`,
   `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `ADMINS`. In production
   From is `biwak@biwak.feinheit.app` (decided 2026-11-21),
   `REPLY_DOMAIN=biwak.feinheit.app`.

Rolling back: `EMAIL_URL` back to an SMTP URL; the outbox sends through
it.
