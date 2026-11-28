# Auditing and logging: where to look

What Biwak records, so that when something comes up ("who changed
this?", "did she get the mail?", "why didn't my reply arrive?") it's
clear where to look. Written with the user 2026-11-24, when the first
colleague started working with it.

**Status:** built; logging, the category audit and the outbox's 90 days
2026-11-24.

## Who changed what: the audit log

`biwak/audit/`: a PostgreSQL trigger writes every insert, update and
delete of the audited tables into `audit_logged_actions`, with the row
and the changed fields; a deleted row keeps its last content. Kept
forever.

- **Tables:** projects and memberships; items with their detail tables
  (lists, groups, to-dos and assignments, messages, folders, docs,
  uploads and file versions), comments, attachments; message
  categories; users, API tokens, passkeys and two-factor, push devices;
  reactions, bookmarks and links; check-in questions and answers;
  organizations, teams, notification levels. New tables people change
  get `audit_tables()` in a migration (AGENTS.md).
- **Who:** the row's `user_name`. Requests and API tokens set
  `user-<id>-…` (`set_user_name()`, the short name without accents:
  PostgreSQL keeps only ASCII in `application_name`, "Jürg" is "Jurg";
  the history finds the person by the ID), `user-0-anonymous` without a
  sign-in; jobs name themselves: "Send mails", "Fairy tasks", "Resend"
  (incoming mail and delivery events), "Basecamp import". Mail replies
  and forwarded mails run as the person. Saving what was typed live
  names who typed it, whoever caused the save (a pause, a viewer
  opening the page, `fairy_tasks`): one person as usual, several by
  their short names ("Bob, Ada", decided 2026-11-28); the job's own name
  comes back afterwards (`user_name_kept()`). Live doc editing otherwise
  runs as the person, and so do the
  links signed for one person in mails ("Keep open", unsubscribing),
  whoever is signed in in that browser (decided 2026-11-28).
- **Left out on purpose:** timestamps that change all the time
  (`last_login`, `last_used_at`, …), secrets (push
  keys, the calendar token, passkey data), the live doc's working state
  (`collab_*`; the saved doc is audited), check-in occurrences,
  forwarded mails before they're filed (filing creates audited items),
  public links (their events say who shared and stopped, decided
  2026-11-24: one place is enough), and events, notifications and
  subscriptions, which are a log themselves or change too often.
- **Reading it:** the admin's "Logged actions" (filter by table and
  action); for one item its "History" (the "More" menu, staff only),
  which condenses it with text diffs (`feed.md`).

## What happened: events

`activity_event`, one row per action in people's words (created,
completed, assigned, moved, shown to clients, shared publicly, …), the
source of the feed, the timelines, the lantern and mails. Kept forever.

## Who was told: notifications and mails

- **Notifications** (`activity_notification`): one row per person and
  event; `sent_at` says when it was mailed, `pushed_at` when pushed.
  "Did Urs hear about this?" Kept forever.
- **Outgoing mails** (admin "Outgoing mails", `outbox/`): every mail
  with its kind, recipients, state, attempts, last error and Resend's
  ID; the content only until the transport accepted it. Deleted after
  **90 days** (decided 2026-11-24, 30 before: "did she get the
  invitation?" a few months later). Bounces and complaints mark the
  person (`mail_undeliverable_at`, shown on their page).
- **Incoming mails** (admin "Inbound messages"): replies and forwarded
  mails with their status, error and sender, 90 days; reply addresses
  in "Reply tokens".

## Signing in

allauth's user sessions: each session with IP, browser and last
activity, listed in the person's settings. Security changes (sign-in
methods, the address) mail the person, so they're in the outbox. API
tokens record `last_used_at`. Failed sign-ins are rate-limited by
allauth but not recorded; single requests only in the server's access
log.

## Errors and log lines

- **Sentry** (`SENTRY_DSN`): uncaught exceptions and everything logged
  at error level: mails or digests that couldn't be built, a daily task
  failing, a live doc not saved, an incoming mail not fetched, the
  outbox giving up on mails.
- **The pod's output** (decided 2026-11-24, `LOGGING` in
  `settings.py`): the `biwak` loggers from info up, with time, level and
  logger: each incoming mail's result, attachments left out of forwarded
  mails, failed pushes, mail sends retried, unknown delivery events, live
  doc warnings. How long it's kept depends on the cluster. Tests print
  warnings only.
- **Daily:** `check_visibility` in `fairy_tasks` mails the admins when
  stored visibility and the item tree disagree.

## Sizes

The audit log, events and notifications grow without pruning; at the
size of one agency that's fine for years. Revisit when the database
grows noticeably.
