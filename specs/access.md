# Access: client visibility and sign-in

**Status:** built (2026-11-20), reviewed twice for visibility
(2026-11-20) and for partners (2026-11-21); the rules marked "after the
visibility review" came from those reviews.

The most delicate part of the app: a bug here shows internal content to a
client. One function decides visibility, everything uses it, and tests go
through every entry point (`AGENTS.md`).

## Who sees what

- **Projects are all-access or limited** (decided 2026-11-20, like
  Basecamp):
  - **All-access**: every own staff member can open the project, see
    everything in it and join it with one click.
  - **Limited**: only members see it; staff join by invitation. For
    what not everybody should see (HR, finances, some client projects).
  - Admins see the list of all projects, limited ones included, and can
    add themselves, recorded as an event in the project; they don't see a
    limited project's content without joining. Memberships are read-only
    in the Django admin, so joining always goes through the app and its
    event (after the visibility review). Joining, on the page and through
    the API, takes the projects one can open plus the limited ones the list
    offers (`projects_to_join()`), not archived limited ones.
  - Losing access (removed from a limited project, an all-access project
    made limited, leaving the own organization) drops the person's
    subscriptions in the project; all through operations
    (`remove_member()`, `update_project()`, `forget_lost_access()` in
    `biwak/projects/operations.py`). Open pages and editors check their
    access again.
- **Staff** with access to a project see everything in it.
- **Partners see only their projects** (decided 2026-11-21,
  `organizations.md`): staff whose organization isn't the own one
  (freelancers, partner agencies) and staff without an organization
  (individuals) see only the projects they're members of; all-access
  projects open only to the own organization's staff. The own
  organization always exists and admins are always in it
  (`User.is_partner`, `User.sees_all_access`, `own_staff()`).
  `Project.objects.accessible_to()` and `notify.people_who_see()` decide
  it, so pages, the feed, search, the palette, the lantern, mails, mail
  replies, the API, the CLI and both websockets follow. Partners are
  assigned and mentioned in all-access projects only as members.
  - **Partners know all the people of their projects** (changed
    2026-11-21, it was "members only, like clients"), like staff of a
    limited project: the members and the own staff of an all-access
    project (`knows_people_of()`, `Project.people_q()`), in the `@` list,
    mentions written and read, assignees, subscribers, check-in askees,
    names in histories, mails and the feed (`Project.people_known_to()`,
    `mentions.known_to()`). Nobody outside their projects: the People
    page, person pages and images go by `known_people()`; a person's feed
    and the palette's people by the projects shared as members, as for
    own staff (`people_visible_to()`). Inactive own staff count as the
    project's people (names in histories); the old title of a list moved
    out of sight shows in the feed only to own staff. Errors naming
    people by ID say nothing about who exists.
  - Partners don't create projects, add or invite people or manage
    organizations: those forms offer everybody (decided 2026-11-21).
  - Admins manage the internal team and partners, staff the clients
    (decided 2026-11-21, `organizations.md`, `org_ops.can_touch()`).
- **Clients** are never covered by all-access: they see a project only
  if they're members, and in it only what is visible to clients.
- **Visible to clients** is a switch on containers (lists, folders), on
  messages, docs and files in the root folder, and on check-in
  questions. Children of a container inherit it and have no switch of
  their own. Off by default: better to show too little once.
- **Comments** on a visible item are visible. No internal comments on
  visible items (decided 2026-11-20: too easy to get wrong).
- **What clients create:** to-dos, comments and messages where they can
  see, and answers to check-ins they're asked; visible by definition.
  Lists, groups (in lists they didn't create), folders, docs and files
  are staff only, through the pages and the API (403; 404 first where the
  place itself is hidden), and clients don't get the forms
  (`ops.can_create()`, after the visibility review). Anything else
  clients change only if they created it (`can_change()`), also what they
  created before that rule.
- **To-dos are shared work:** clients change every field of a visible
  to-do (title, notes, assignees, due date, repeat rule), also of to-dos
  staff created (decided 2026-11-20; `can_change()` covers renaming,
  archiving and trashing, not to-dos' fields). Moving is part of it:
  clients move visible to-dos by dragging, with "Move to…" and through the
  API, only into lists they can see, so a move never hides a to-do from
  them (confirmed 2026-11-21).
- **Assigning:** a client can be assigned only to a visible to-do. Staff
  can be assigned wherever they can see the to-do; assigning someone who
  isn't a member adds them to the project (recorded as added, decided
  2026-11-21, `ops.assignable_people()`). Clients assign members only.
- **Clients learn about the project's members only** (not partners,
  above), not about staff who see the project because it's all-access
  (after the visibility review): subscribers on item pages, the people a
  check-in asks and who hasn't answered (`Project.people_known_to()`).
  People removed from the project who stay assigned to to-dos aren't
  named to clients and partners either: the rows, the to-do's page, the
  API's `assignees` and mails show only the people they may know (fixed
  2026-11-21 after a review: `{% known_in %}`, `known_ids_for()`). The
  feed API's event data (`mentioned`, `assigned`, `people`, `assignees`,
  by ID) lists only those too (`event_out()`).
  Both halves of the rule (after the second visibility review):
  - **People who act in a visible place are shown by name**, members or
    not: comment authors, reactions, presence in the live editor. That
    only happens in all-access projects; limited projects only have
    members.
  - **Clients can't look up people who haven't acted:** the `@` list
    offers members only. When a client writes (pages, API texts, check-in
    answers, mail replies), `mentions.resolve()` and `mentions.update()`
    resolve, subscribe and notify members only; `@Bob`,
    `@bob@example.org` or a guessed `[@x](person:N)` of anybody else stays
    plain text and notifies nobody. When a client reads (pages, titles,
    search, `*_html`, mails), names of non-members show as the label
    written, never the current name, so guessing IDs lists nobody. The
    reader is the request's person (the middleware, also for API tokens)
    or the mail's recipient (`mentions.reading_as()`); without one, texts
    render as for a client.
- **Turning visibility off** hides the content again, including comments
  clients wrote; the question says so.

## One check

`Item.objects.visible_to(person)` and one object-level check
(`item_for()` for views and the API), used by every view, the feed,
search, notifications, mail replies, the API and exports. No view
filters on its own. Tests go through every entry point as a client and
as staff, including items moved between visible and internal containers.

**Stored, not computed on read** (decided 2026-11-20): each item stores
its effective visibility (`biwak/items/visibility.py`), so the check is
a plain filter on a column plus project access, with no recursive query
on the hot path.

- Recomputed for the subtree whenever a switch changes, an item moves or
  is created, in the same transaction.
- Comments, files attached to texts and events follow their item.
- **Events store whether their item was visible when they happened**
  (`Event.is_client_visible`, after the visibility review): events keep
  the title at the time, assignees and people mentioned, so a to-do
  created internally ("Raise the rate for Cleo"), renamed and moved into a
  visible list mustn't show clients its internal past. Clients see an
  event only if it was visible then and its item is visible now
  (`Event.objects.visible_to()`). An edit merges only into an event of the
  same visibility, so a visible event never takes in internal edits.
  Events from before this rule count as internal. The feed's filter, the
  API's `visible_to_clients` of an event and the feed agree.
  Notifications too: `notify()` leaves clients out of an internal event
  even if the item became visible before it ran, and `mails._deliverable()`
  (item mails and digests) drops a client's notification of an internal
  event.
- **Drift** is the risk: tests compare the stored value with the one
  computed from the tree after every kind of change, and
  `check_visibility` does the same on real data, daily in `fairy_tasks`,
  mailing admins on any difference.

## Making it obvious

Like Basecamp's bright yellow:

- A badge on everything visible to clients wherever it's listed (lists,
  to-dos, messages, docs, files, search results, the to-dos by date); not
  in the feed and the lantern (`feed.md`).
- **The client tab** (decided 2026-11-21, like Basecamp's): the page of
  something visible to clients shows a slim tab at the window's right
  edge that stays while scrolling, "Clients can see this."
  (`items/_client_tab.html`, `.wb-client-tab`), instead of a banner
  taking a line of the page. No banner above the comment form. Forms in
  modals keep the banner (`items/_client_banner.html`): the dialog
  covers the page. Forms on pages of their own (without JavaScript, the
  edit pages of messages, files and check-ins) have the tab (decided
  2026-11-22). On phones the tab starts below the navigation's two rows,
  and the navigation's menus open above it. Editing a project with active client members says
  "The clients of this project can see this." (`clients_see` in
  `project_edit`, `modal_form.html`).
- **Showing to clients asks first, hiding is one click** (decided
  2026-11-21): `GET /items/<pk>/switch/` is the question (a page, a modal
  for `HX-Modal`; an item already visible redirects to itself), saying
  what changes: "Makes this list, 12 to-dos and 34 comments visible to 3
  clients." The text is built per kind by the view (`_show_texts()`,
  `visibility.affected()` in `biwak/items/views.py`), so the switch
  include shows no sentence by the button. It counts neither drafts
  (anybody's, only their creators see them) nor what's in the trash
  (decided 2026-11-21). The POST with `visible=1`
  shows the item, without it hides it. Staff only (403 for clients).
- Notification mails about visible items say so in the first line.
- API and CLI output include the visibility (`visible_to_clients`); the
  agent skills, when they come, tell agents to check it before writing.

## Sign-in

No single sign-on as the only way in: not every client has a Google or
Microsoft account (decided 2026-11-20). No passwords: allauth's password
pages answer 404 (`biwak/urls.py`); add them only if somebody really
needs them. Nobody signs up: people are invited (`activation.md`).

**django-allauth** instead of Governance's `django-authlib` (decided
2026-11-20): codes, passkeys, authenticator apps, Google and Microsoft in
one maintained package (`biwak/settings.py`, `biwak/accounts/`).

The ways in, each specified in one place:

- **A code by mail** (allauth's login by code, 10 minutes, single-use):
  everybody, unless their organization requires single sign-on. A code
  works when the mail is read on the phone and the app is open on the
  laptop, which a link doesn't.
- **A passkey** (WebAuthn): a way in alone, not a second factor
  (`two-factor.md`).
- **The organization's identity provider** (Google Workspace, Microsoft
  Entra ID), allowed or required per organization (`sso.md`). The own
  organization allows Google.
- **An authenticator app** is an optional second factor after a code or
  the identity provider, never after a passkey; organizations may
  require a second factor (`two-factor.md`).

**The sign-in page** (`LOGIN_URL`, allauth's code page, our template
`account/request_login_code.html`): the address for a code and "Sign in
with a passkey" right there; single sign-on a little out of the way,
behind "Sign in through your organization" (decided 2026-11-21).
allauth's pages we show (signing in and out, codes, confirming access,
the identity providers' pages) are overridden in `biwak/templates/` to
say things in sentence case like the rest ("Sign in", "Remember me";
fixed 2026-11-22, `accounts/test_sentence_case.py`).

**The passkey offer** (decided 2026-11-20: once, dismissable;
`biwak/accounts/passkeys.py`): the first page opened after a sign-in by
code leads to `/accounts/passkey-offer/` (and on to where they were
going), unless they have a passkey, dismissed it, or their organization
requires single sign-on. "Not now, don't ask again" and adding a passkey
set `User.passkey_offer_done`, which ends the offer for good; leaving
the page any other way brings it back after the next sign-in by code.
Not after passkey or single sign-on sign-ins, not for API and htmx
requests. Clients get it too.

**Addresses:** everybody's address is allauth's verified primary
address (`User.verify_email()`, also when it changes): allauth confirms
who someone is before adding a passkey (by code, sent only to verified
addresses; with an authenticator app by the app or a passkey,
`two-factor.md`). A changed address replaces the old one (after the second
visibility review): the old one no longer signs in and can be given to
somebody else. Nobody changes their own address (allauth's address pages
answer 404, `sso.md`); admins do (`mail-sending.md`).

**Sessions** (`biwak/settings.py`): in the database, 30 days, renewed
with every request; shorter where single sign-on is required (`sso.md`).
The settings page's "Sign-in" section (`accounts/settings.html`,
`biwak/accounts/signin.py`) shows:

- passkeys (name, added, last used, Remove, "Add a passkey" through
  allauth's flow), the authenticator app (`two-factor.md`) and the
  connected Google and Microsoft accounts (`sso.md`);
- the sessions, this one first: browser and device from the User-Agent,
  IP and when it signed in (`USERSESSIONS_TRACK_ACTIVITY` is off, decided
  2026-11-21: it writes the session's row on every request); "Sign out"
  on each other one (`session_end`, our view, since allauth only ends all
  others) and "Sign out everywhere else"; "Sign out" in the "Me" menu
  signs out of this browser;
- a link to the API tokens page.

allauth's `/accounts/2fa/…` and `/accounts/sessions/` pages lead there.

**Also:**

- Links in notification mails lead to the item, through the sign-in if
  needed.
- Rate limits on codes per address and per IP (allauth's defaults); no
  response says whether an address exists (`ACCOUNT_PREVENT_ENUMERATION`).
- Deactivated people can't sign in by any way (`activation.md`).
- Staff or client is a property of the person, set by admins; everybody
  can belong to an organization (`organizations.md`), shown for clients
  and partners: "Ada, Example Ltd".
