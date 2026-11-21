# Sending mail through Resend, with an outbox

The idea (2026-11-21): move sending to Resend soon (the backlog's
"Sending through Resend" in `SPEC.md`), and with it queue outgoing mail
in the app, since the cluster's postfix (today's queue and retries) is
out of the way then.

**Status:** spec (2026-11-21), the questions answered the same day.
Being built (2026-11-21, branch `mail-sending`): the outbox, see
"Built".

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

## Built

Decisions made while building (2026-11-21, by the building agent; the
conservative choice where the spec was open):

- **One app,** `biwak/outbox/`: `OutgoingMail` (`models.py`),
  `sending.py` (`send()`, `deliver()`, `retry()`, `prune()`), the Resend
  backend (`resend.py`), a read-only admin with a state filter (waiting,
  sent, given up) showing the kept content.
- **Explicitly, not as Django's default mailer:** the app's mails call
  `outbox.send(message, kind)` instead of `message.send()`; the default
  mailer stays the transport (`EMAIL_URL`) the outbox sends with. So
  `mail_admins` and Django's error mails go around the outbox by
  themselves, and the tests keep Django's locmem mailer: the outbox runs
  in every test, `mail.outbox` gets what it sends. allauth's mails go
  through the account adapter's `send_mail()`.
- **Production:** `EMAIL_URL=resend:` switches the transport to Resend's
  API (`biwak.outbox.resend.EmailBackend`, anymail's with the
  `Idempotency-Key` header and Resend's own tag `kind`; anymail's tags
  would be an `X-Tags` header), with `RESEND_API_KEY` and a 10 second
  timeout. Not switched on by `RESEND_API_KEY` alone: that key is there
  for replies already, and sending must wait for the domain's
  verification.
- **In the transaction of the change:** notification mails and digests
  are put into the outbox in the transaction that marks their
  notifications sent, invitations in the one inviting, the answer to a
  refused reply in the one recording it, login codes in the request's.
  Check-in mails are still built after the commit (they look at who sees
  the question then) and put into the outbox one by one.
- **The first attempt** is the one after the commit; a new row is due for
  `retry()` only a minute later, so the two don't race for it (and a
  crash before the first attempt is caught up a minute later).
- **Locking:** `deliver()` locks the row (`select_for_update(skip_locked)`)
  for the attempt, a short HTTP request; whoever doesn't get the lock
  skips the row. A crash after Resend accepted and before our commit
  leaves the row waiting: the retry sends the same `Idempotency-Key`
  (`<host>/outgoing-mail/<id>`: the host because installations may share
  a Resend account) and Resend answers with the first mail's ID instead
  of sending it again. Resend keeps keys for 24 hours, which is why
  nothing is tried after 24 hours: such rows are given up without another
  attempt. With other transports (SMTP) that crash would send twice.
- **Backoff:** after the first failure 1 minute, then 2, 5, 10, 30 minutes,
  then hourly; given up at the first retry 24 hours after it was queued.
  Resend's rate limit (HTTP 429) isn't counted as a failed attempt: the
  row waits a minute and the run stops there. At most 200 retries a run.
- **Giving up** tells the admins in one mail per `send_mails` run listing
  the mails (kind, recipients, subject, attempts, last error) with a link
  to the admin, through the plain mailer, and logs an error (Sentry).
  Login codes past their ten minutes (`ACCOUNT_LOGIN_BY_CODE_TIMEOUT`)
  are given up quietly: nothing for an admin to do. allauth's mail to an
  address without an account asking for a code counts as a login code.
- **Kinds:** `notification`, `digest`, `checkin`, `login-code`,
  `invitation`, `reply-refused`, `account` (allauth's other mails, none
  switched on today), and `admin` only as Resend's tag of `mail_admins`.
- **Kept:** the content until the transport accepted the mail, then only
  bookkeeping (recipients, kind, Resend's ID, attempts, last error, the
  delivery state). `fairy_tasks` deletes rows 30 days after they were
  queued. Attachments are stored in the row too (base64); none of our
  mails have any today.
- **Delivery events** come to the existing `/inbound/resend/` (the same
  Svix secret; `biwak/outbox/events.py`): `email.delivered`,
  `email.bounced`, `email.complained`, matched to the row by Resend's ID
  (events about mails we don't know are ignored). The row keeps the worst
  state so far (delivered < bounced < complained), so a late `delivered`
  doesn't hide a bounce. The webhook answers them whenever
  `RESEND_WEBHOOK_SECRET` is set, also while replying is off (received
  mails still answer 404 then).
- **Hard** means a complaint, or a bounce of `type` `Permanent` (Resend:
  `Permanent` or `Temporary`); a temporary bounce is noted on the row
  only. The addresses marked are those of the event's `to` that are the
  row's recipients (all of the row's if none match).
- **`User.mail_undeliverable_at`,** not allauth's `EmailAddress`: a person
  has one address (`User.email`, mirrored into `EmailAddress`), the mails
  go to it, and the queries that pick who gets mail are on `User`. It's
  cleared when `User.email` changes (`User.save()`), by editing the field
  in the admin, or with the admin action "Mail to the selected people
  works again" (the People list filters by it). The audit log records it
  (`accounts_user` is audited), changes by the webhook as `Resend`.
- **What it stops:** notification mails, digests and check-in mails
  (check-in questions are the same kind of automatic mail). Their
  notifications wait, like those of people with "No mails", and stay in
  the lantern; once cleared, the waiting ones go out with the next run.
  Login codes, invitations and answers to refused replies still go out:
  someone asked for them, and the address may work again.
- **Shown** on the person's activity page to staff and to the person
  (not to other clients), in the admin, and as a warning after asking
  for a login code. That warning tells whoever types the address that
  it bounced: allauth otherwise doesn't say whether an address has an
  account (an open question below).
- **No audit log** for `OutgoingMail`: only the system writes it (the
  outbox and Resend's webhooks); the admin is read-only.

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
