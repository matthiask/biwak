# UI round 6: finding people, inviting several, subscribing is the switch

Round 6 of `ui-feedback.md` (2026-11-21), the questions answered the same
day.

**Status:** spec (2026-11-21), all details confirmed the same day.
Part A built (2026-11-21): `ComboboxSelect` and `PersonChoiceField`
(`person_label()`) in `biwak/forms.py`, `frontend/combobox.js`, on "Add
someone" (found by the address too), the feed's person filter and the
check-in's time zone; browser test `biwak/test_e2e_combobox.py`.

**Agent:** a cheaper model for part A; parts B and C touch who may do
what and who's told: a cheaper model with the visibility and
notification tests reviewed, or a strong one.

**Depends on:** `organizations.md` (organizations, `for_new_person()`),
`subscribers.md`, `notifications.md`.

## A. Finding a person: a combobox

"Add someone" on a project's people page lists everybody active (about
1500 people in production): too long for a plain select.

- **Copy Workbench's `ComboboxSelect`** (decided 2026-11-21;
  `~/projects/sites/workbench/workbench/tools/forms.py` and
  `initCombobox` in its `static/workbench/main.js`; Workbench is the
  user's code, adapting it is fine, `AGENTS.md`): the select gets a
  search field that finds the typed words anywhere in the option (the
  name, the organization, the address), keyboard and mouse, wrapping
  long options. Without JavaScript it stays the plain select.
- The options say who someone is: "Ada Example · Example Client Ltd"
  (the organization, for staff "staff" or the own organization's name).
- **Where** (decided 2026-11-21: reuse it wherever a select gets long):
  the single selects that list many choices today:
  - "Add someone" (`AddMemberForm`, every active person);
  - the person filter of the feed (`activity/views.py`, everybody
    sharing a project with the viewer);
  - the time zone of a check-in (`checkins/views.py`, about 400 zones).
  Not: the assignee picker (`AssigneeSelect`, its own widget over a
  project's members), the checkbox lists of a project's or an
  organization's people (new project, check-in's people asked, files'
  "these people"), the organization field (a text field with a
  `datalist`, which finds already). Same widget, `data-combobox`, one
  script (`frontend/combobox.js`); a new long select gets it too.
- **Built** (2026-11-21): staff without an organization (individual
  partners) say "staff"; clients without one only their name. Only "Add
  someone" finds people by their address (`data-search`, staff managing
  members see addresses anyway); the feed's filter, which clients have
  too, doesn't. The list looks like the `@` list (`wb-mentions`) and
  closes on Escape (not the modal) and when the field loses the focus.
- 1500 options in the page are fine (decided 2026-11-21: about 100 KB, filtered
  in the browser); a server-side autocomplete only if it gets slow.

## B. Inviting several people at once

Today "Invite by email" on a project's people page invites one person to
that project; an invited person is an account that has never signed in,
shown nowhere as such.

### The flow

- **One flow, two entry points** (decided 2026-11-21):
  - "Invite people" on `/people/` (staff), choosing the projects in the
    form;
  - "Invite by email" on a project's people page opens the same form
    with that project chosen.
- **A row per person** (decided 2026-11-21): email, name, organization
  (suggested from the address's domain as `for_new_person()` does,
  changeable, empty allowed), and for admins staff or client; "Add
  another" adds a row (a formset, rows added by a small script, without
  JavaScript a few empty rows).
- **The projects:** one set for all rows (several projects allowed, the
  ones the inviter can manage members of); people needing other projects
  are another round. With each project the "Notified by default / Only
  when tagged" choice of `notifications.md`, once for the round.
- **Sending:** one invitation mail per person (after the commit, as
  today), naming all the projects; people who already have an account
  are added to the projects and get the "added to" notification as
  today, no invitation.
- **Errors per row** (an address of a deactivated person, staff invited
  by a non-admin, an organization they may not touch): the whole round
  is saved or nothing, the form shows each row's error.
- Same rules as `invite()` today: only admins invite staff and put
  people into the own organization; clients don't invite.
- API and CLI (decided 2026-11-21): `POST /api/v1/invitations/` with a list of people and
  projects; `biwak invite EMAIL… --project ID…`. The old single-project
  endpoints stay (they call the same operation).

### Invitations visible

An **invitation** is a person who has never signed in (`last_login` is
empty) and was invited (keep who and when: `invited_by`, `invited_at` on
the person, set by `invite()`).

- **Marked** (decided 2026-11-21): "Invited, not signed in yet" next to
  the person on the project's people page, on `/people/` and their
  person page, with who invited them and when.
- **Resend** (staff): sends the invitation mail again, naming the
  projects they're in now; "Sent again." No limit in code (decided 2026-11-21: people
  shouldn't be annoying).
- **Filter on `/people/`:** "Invited" lists everybody who hasn't signed
  in yet, oldest invitation first.
- **Withdraw** (decided 2026-11-21: staff, only while they haven't
  signed in): removes the person's memberships, and the account itself if
  nothing else refers to it (no comments, no assignments by others, no
  other projects); else only from these projects, with the question
  saying so. A confirmation modal ("Withdraw the invitation?"). The
  feed's "added" events stay.

## C. Subscribing is the switch

On a single to-do (message, doc, file), notifications and subscribers
were two settings: confusing (user, 2026-11-21: "when I'm a subscriber,
I will be notified").

- **Subscribed means notified of everything on the item** (decided
  2026-11-21, like Basecamp: "when you're selected then you get all
  follow-ups. You can always unsubscribe"). Every subscription counts the
  same, also the automatic ones (posting to everybody, commenting,
  being assigned or mentioned).
- **Unsubscribing** is how to stop hearing about one item.
- **"Notifications…" leaves the items' "More" menu** and the level
  override on items goes (`LevelOverride` with an item that isn't a list;
  existing rows deleted in a migration: no users yet). The item's page
  shows "You're subscribed / Subscribe" in the subscribers card, as today.
- **Levels stay on projects and lists,** and decide **who gets subscribed
  automatically** and what's new there (a new to-do in a list, a new
  message): "Everything" subscribes the person when something is posted
  to everybody; "Only what concerns me" ("Only when tagged") doesn't
  subscribe them then, only being mentioned, assigned or their own
  things do; "Nothing" subscribes them only when they act themselves
  (comment, are assigned) (decided 2026-11-21). That replaces "the level holds the mails
  back" in `notifications.md`, which changes with this part.
- Mails, digests and the lantern follow the subscriptions; mentions
  still notify on every level except "Nothing" (as today).
- Tests: the old level filter's cases rewritten as subscription cases
  (subscribed with "Only what concerns me" gets the comment; not
  subscribed doesn't), posting to everybody per level, the item's More
  menu without "Notifications…", the migration.

## Done when

- A: the combobox on "Add someone" and the other long people selects,
  with a browser test for the filtering (JavaScript) and the plain select
  without it.
- B: the invite form from both entry points, several rows and projects,
  per-row errors, all or nothing; the invitations marked, resent,
  filtered, withdrawn; tests through the pages, the API and the CLI,
  as staff, admin and client (clients can't), mails after the commit.
- C: as above; `notifications.md` and `subscribers.md` say so.
- The help (`docs/`: people and invitations, notifications) says what
  changed.
