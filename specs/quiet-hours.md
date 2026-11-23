# Quiet hours and out of office

Mails wait while people aren't working: outside their working hours
(like Basecamp's "Work can wait") and while they're away. Decided with
the user 2026-11-22.

**Status:** built (2026-11-22).

## One time zone

The installation's (`TIME_ZONE`) for working hours and away dates; no
time zone per person (decided 2026-11-22: Biwak is for working
together, so the shared time matters more than the local one, and DST
doesn't change everywhere on the same day). Check-ins use it too: their
own time zone per question goes (`checkins.md`, decided 2026-11-22).

## Quiet hours

- **Per person, off by default** (decided 2026-11-22): working days
  (Monday to Friday preset) and hours (08:00–18:00 preset, in the
  installation's time zone) in Settings
  under Notifications; the API (`GET/PUT /api/v1/me/notifications/`)
  and CLI (`biwak notifications --quiet-hours …`) too. The fields on
  `User`: `quiet_hours`, `working_days`, `working_from`,
  `working_until`; when mails wait: `biwak/accounts/quiet.py`.
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
- **Check-in summaries are held** (decided 2026-11-22) during quiet
  hours and while away, like other mails: `summarize_due()` keeps a
  `HeldSummary` per person whose mails wait, `send_held_summaries()`
  (part of `checkins.run()`, so of `send_mails`) mails it once they may
  get mail again, as its own check-in mail next to the rest.
- **People away aren't asked check-in questions** (decided 2026-11-22):
  no question mail, not among the occurrence's people asked, so not
  missing in it (`_ask()`; away on the day it's asked, in the
  installation's time zone). Quiet hours don't keep questions back.
- **Delivery "daily digest"** sends the digest at the start of the
  first working time of the day instead of its fixed time when quiet
  hours are on. "None" stays none.
- Where it's decided: in the sending loop (`send_mails`): a
  notification whose recipient is in quiet time is left unsent and
  looked at again on later runs; nothing is dropped.

## Out of office

- **"Away until <date>"** with an optional note (one line, at most 200
  characters), set by the person in Settings ("Out of office"), by
  admins for others (when someone forgot), and in the API (`PUT/DELETE
  /api/v1/me/away/` and `/api/v1/people/{id}/away/`, `away_until` and
  `away_note` on every person) and CLI (`biwak away`). Ends by itself
  the day after the date; "I'm back" ends it early. `User.away_until`,
  `User.away_note`; `set_away()`/`end_away()` in
  `biwak/accounts/operations.py`.
- **Shown** (decided 2026-11-22): their mark gets a small away sign
  and the title "Away until 3 Dec: <note>"; the people picker, the `@`
  list and teams' entries say "away until 3 Dec"; assigning or
  mentioning them shows the note once in the form ("Ada is away until
  3 Dec: back on the 4th, ask Bob meanwhile"). Their person page says
  so. An open to-do's page shows that note under "Assigned to" for
  each assignee away, overdue or not (decided 2026-11-23: overdue
  to-dos especially, but useful on all; not once it's completed). Not a reason to leave them out: they can still be assigned.
- **Mails held** (decided 2026-11-22): nothing is mailed while away
  (also not digests); the lantern collects as usual. When the away
  time ends, one digest of what happened meanwhile goes out (grouped by
  project, like digests), respecting quiet hours.
- Clients see the away sign and note of people they may know, like the
  mark itself.

## How it's built (2026-11-22, confirmed by the user the same day)

- **Held, then one mail** (`hold()` and `_send_held()` in
  `biwak/activity/mails.py`, `Notification.held_at`): every
  `send_mails` run marks the unsent notifications of people whose
  mails wait now (`hold()`: away today, or quiet hours and outside the
  working time) with `held_at`, and
  leaves those people out. Once they may get mail again, what's held
  goes at once: one digest-form mail (`digest_mail()`, kind `digest`),
  or the usual item or batch mail when it's one mail's worth (one item
  or one batch). Nothing depends on remembering when the quiet time
  started, so "I'm back", turning quiet hours off and changing the days
  all just work. Notifications read in the lantern meanwhile aren't
  mailed, as before; switching to "No mails" keeps them unsent.
- **Digests** with quiet hours: due whenever the person is in their
  working time (so at its start on working days), with the
  notifications before today's midnight and everything held; without
  quiet hours at 07:00 as before, plus what was held while away.
- **Working time:** `working_from` inclusive, `working_until`
  exclusive, both on the same day (no working time over midnight; quiet hours
  need a working day, turning them off keeps the days and hours);
  `working_days` as `date.weekday()` (0 Monday). Away ends at the
  installation's midnight after `away_until` (without quiet hours the
  mail after being away goes then, a digest at 07:00); nothing clears the
  fields, `is_away` compares with today.
- **Away for others:** admins only (`can_set_away()`), on the person's
  page ("Set away…" as a modal, `organizations.people.person_away`;
  "End away" while away) and the API; not for oneself there (the settings) and not for inactive people.
- **One mail's worth:** "as usual when only one is waiting" means one
  item, or one batch of files or assigned to-dos. What waited goes at
  the start of the working time without the 10-minute merge. Digests
  have no cap, so neither has the mail after being away.
- **Wording:** "Out of office" (the settings' heading), "I'm back",
  "Welcome back.", "Set away…" and "End away" (admins), "Set Ada away"
  (the modal), "In the time zone Europe/Zurich, the same for
  everybody."; German "Ruhezeiten", "Abwesenheit", "Abwesend bis 3.
  Dez.: …", "Ich bin zurück". The CLI's `members` and `people` show
  "(away until 2026-12-03)" after the name.
- **Shown:** a small moon (`bi-moon-fill`) on the mark's lower right
  (`{% avatar %}`, `frontend/avatar.js`);
  the mark's title is the name and on a second line "Away until 3 Dec:
  <note>" (the date with the year when it isn't this one). Pickers and
  the `@` list add "away until 3 Dec" to the entry; the team's page and
  the People page's teams section after the member. The note shows in
  the form below the field (`.wb-away-notes`, `frontend/away.js`), once
  per person and form,
  also for each member when a team is picked. "Teams' entries" are the
  members on a team's page and in the People page's Teams section.
