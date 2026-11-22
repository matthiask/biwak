# Quiet hours and out of office

Mails wait while people aren't working: outside their working hours
(like Basecamp's "Work can wait") and while they're away. Decided with
the user 2026-11-22.

**Status:** open.

Depends on: `notifications.md` (mails and digests, `User.mail_delivery`),
`mail-sending.md` (the outbox), `lantern.md`, `people.md` (the mark),
`todos.md` (the people picker), `teams.md`, `keyboard.md` (the settings
page), `checkins.md` (asking), `languages.md`.

## One time zone

The installation's (`TIME_ZONE`) for working hours and away dates; no
time zone per person (decided 2026-11-22: Biwak is for working
together, so the shared time matters more than the local one, and DST
doesn't change everywhere on the same day). Check-ins keep their
question's time zone (`checkins.md`).

## Quiet hours

- **Per person, off by default** (decided 2026-11-22): working days
  (Monday to Friday preset) and hours (08:00–18:00 preset, in the
  installation's time zone) in Settings
  under Notifications; the API (`/me/notifications/`) and CLI too.
- **Mails only:** the lantern in the app keeps everything as it
  happens. Outside working time, notification mails and digests wait;
  at the start of the next working time they go out as **one mail**
  (the digest's form: everything that happened, grouped by project),
  or as usual when only one is waiting.
- **Nothing bypasses** (decided 2026-11-22): mentions and "Tell them
  now" wait too.
- **Not held:** sign-in codes, security mails, invitations, mail reply
  errors, check-in questions (they're asked at their own time, which
  the person can set). Bounce handling unchanged.
- **Delivery "daily digest"** sends the digest at the start of the
  first working time of the day instead of its fixed time when quiet
  hours are on. "None" stays none.
- Where it's decided: in the sending loop (`send_mails`): a
  notification whose recipient is in quiet time is left unsent and
  looked at again on later runs; nothing is dropped.

## Out of office

- **"Away until <date>"** with an optional note (one line, at most 200
  characters), set by the person in Settings, by admins for others
  (when someone forgot), and in the API and CLI. Ends by itself the
  day after the date; "I'm back" ends it early.
- **Shown** (decided 2026-11-22): their mark gets a small away sign
  and the title "Away until 3 Dec: <note>"; the people picker, the `@`
  list and teams' entries say "away until 3 Dec"; assigning or
  mentioning them shows the note once in the form ("Ada is away until
  3 Dec: back on the 4th, ask Bob meanwhile"). Their person page says
  so. Not a reason to leave them out: they can still be assigned.
- **Mails held** (decided 2026-11-22): nothing is mailed while away
  (also not digests); the lantern collects as usual. When the away
  time ends, one digest of what happened meanwhile goes out (grouped by
  project, capped like digests), respecting quiet hours.
- Clients see the away sign and note of people they may know, like the
  mark itself.

## Done when

- Working days and hours, and away are set in Settings, the API and
  the CLI; admins set away for others.
- Notification mails and digests outside working time or while away
  wait and go out as one mail at the next working time or on return;
  the excluded kinds go at once; nothing is lost (tests with frozen
  time, including the days DST changes).
- The away sign and note show on marks, pickers, the `@` list, teams,
  the person page and when assigning or mentioning (browser tests for
  the pickers).
- Help (notifications, people) and the German catalog updated.
