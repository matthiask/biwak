# Access: client visibility and login

**Status:** built (2026-11-20). The separate review of the visibility
checks (2026-11-20) found leaks and missing permission checks, fixed with
the decisions marked "after the visibility review" here and in the specs
of the parts; the fixing agent's choices confirmed 2026-11-20 (merged
edits never cross visibility, existing events count as internal, clients
keep changing what they created before, raw notes in the to-do form).

The most delicate part of the app: a bug here shows internal content to a
client. One function decides visibility, everything uses it, and the
tests are thorough. Built in the core phase; reviewed separately before
the first client gets a login.

## Who sees what

- **Projects are all-access or limited** (decided 2026-11-20, like
  Basecamp):
  - **All-access**: every staff member can open the project and see
    everything in it, and join it with one click. Typical for team-wide
    projects.
  - **Limited**: only members see it at all; staff join by invitation.
    For projects not everybody in the organization should see (HR,
    finances, some client projects).
  - Admins see the list of all projects, including limited ones, and can
    add themselves; that's recorded as an event in the project. They
    don't see a limited project's content without joining. The
    memberships are read-only in the Django admin, so that joining always
    goes through the app and its event (decided 2026-11-20 after the
    visibility review). Joining, on the page and through the API, takes
    the projects they can open plus the limited ones the list offers
    (`projects_to_join()`), not archived limited ones (fixed 2026-11-20
    after the second visibility review: the API took any project).
  - Losing access (removed from a limited project, or an all-access
    project made limited) drops the person's subscriptions in the
    project; both go through operations (`remove_member()`,
    `update_project()`, fixed 2026-11-21 after the code review: making a
    project limited kept them).
- **Staff** with access to a project see everything in it.
- **Partners see only their projects** (decided 2026-11-21,
  `organizations.md`): staff whose organization isn't the installation's
  own (freelancers, partner agencies) see only the projects they're
  members of; all-access projects open only to the own organization
  staff. Staff without an organization are individuals (freelancers) and
  partners too (decided 2026-11-21); the own organization always exists
  and admins are always in it (`User.is_partner`, `User.sees_all_access`,
  `own_staff()` for querysets).
  `Project.objects.accessible_to()` and `notify.people_who_see()` decide
  it, so pages, the feed, search, the palette, the lantern, mails, mail
  replies, the API, the CLI and both websockets follow. Partners are
  assigned and mentioned in all-access projects only as members. In
  the projects they're in, they know all its people, like staff of a
  limited project (changed 2026-11-21, it was "members only, like
  clients"): the members and the own staff of an all-access project
  (`knows_people_of()`, `Project.people_q()`; the `@` list, mentions
  they write and read, assignees, subscribers, check-in askees, names in
  histories, mails and the feed, all through `Project.people_known_to()`
  and `mentions.known_to()`). Nobody outside their projects: the People
  page, person pages and images (`known_people()`); a person's feed and
  the palette's people go by the projects shared as members, as for own
  staff (`people_visible_to()`). They don't create
  projects, add or invite people or manage organizations, whose forms
  offer everybody (decided 2026-11-21). Admins manage the internal team
  and partners, staff the clients (decided 2026-11-21): moving people in
  or out of the own organization or a partner organization (one with
  staff), moving staff at all, inviting into them, merging them and their
  domains are for admins only (`org_ops.can_touch()`). Leaving the own
  organization drops
  the subscriptions in projects one can't open anymore, and open pages
  and editors check their access again.
- **Clients** are never covered by all-access either: they see a project only
  if they're members, and in it only what
  is visible to clients.
- Visible to clients is a switch on **containers** (lists, folders) and
  on **messages, docs and files in the root folder**, and check-in
  questions. Children of a container inherit it and have no switch of
  their own. Off by default: better to show too little once.
- Comments on a visible item are visible. There are no internal comments
  on visible items (decided 2026-11-20: too easy to get wrong).
- Clients can create to-dos, comments and messages where they can see,
  and answer check-ins they're asked; what they create is visible by
  definition. Nothing else: lists, groups (in lists they didn't create),
  folders, docs and files are staff only, through the pages and the API
  (403; 404 first where the place itself is hidden), and clients don't
  get the forms (decided 2026-11-20 after the visibility review, which
  found clients creating lists, folders, docs and files;
  `ops.can_create()`). What clients created before stays theirs to change
  (`can_change()`).
- Assigning a client to a to-do requires the to-do to be visible. Staff
  can be assigned wherever they can see the to-do; assigning someone who
  isn't a member adds them to the project (recorded as added, decided
  2026-11-21, `ops.assignable_people()`). Clients assign members only:
  they don't learn about other staff.
- To-dos are shared work: clients change every field of a visible to-do
  (title, notes, assignees, due date, repeat rule), also of to-dos staff
  created (decided 2026-11-20; `can_change()` covers renaming, archiving
  and trashing, not to-dos' fields). Moving a to-do between lists and
  groups is part of it: clients move visible to-dos by dragging, with
  "Move to…" and through the API, only into lists they can see, so a
  move never hides a to-do from them (confirmed 2026-11-21). Everything
  else clients change only if they created it.
- Clients (not partners, above) learn about the project's members only,
  not about staff who see the project because it's all-access (decided 2026-11-20 after the
  visibility review): subscribers on item pages, the people asked by a
  check-in and who hasn't answered (`Project.people_known_to()`).
  Both halves of the rule (decided 2026-11-20 after the second visibility
  review):
  - **People who act in a visible place are shown by name**, like
    members, whether they're members or not: comment authors, reactions,
    presence in the live editor. That only happens in all-access
    projects, where every staff member may take part; limited projects
    only have members.
  - **Clients can't look up people who haven't acted**: the `@` list
    offers members only, and mentions follow the same rule. When a client
    writes (pages, API texts, check-in answers, mail replies),
    `mentions.resolve()` and `mentions.update()` resolve, subscribe and
    notify members only; `@Bob`, `@bob@example.org` or a guessed
    `[@x](person:N)` of anybody else stays plain text and notifies nobody.
    When a client reads (pages, titles, search, `*_html`, mails), names of
    people who aren't members show as the label written, never the current
    name, so guessing ids lists nobody. Who reads is the request's person
    (the middleware, also for API tokens) or the mail's recipient
    (`mentions.reading_as()`); without one, texts render as for a client.
    Staff write and read as before.
- Turning visibility off later hides the content again, including
  comments clients wrote; the switch says so.

## One check

A single queryset method (`Item.objects.visible_to(person)`) and a single
object-level check, used by every view, the feed, search, notifications,
mail replies, the API and exports. No view filters on its own. Tests go
through every entry point with a client and a staff member and assert
what each sees, including items moved between visible and internal
containers.

**Stored, not computed on read** (decided 2026-11-20): each item stores
its effective visibility, so the check is a plain filter on a column
(plus project access: membership, or all-access for staff), easy to read
and review, no recursive query on the hot path.

- It's recomputed for the subtree (django-tree-queries, `core.md`)
  whenever a switch changes, an item moves, or an item is created, in the
  same transaction.
- Comments, files attached to texts and events follow their item.
- **Events also store whether their item was visible to clients when
  they happened** (decided 2026-11-20, after the visibility review):
  events keep the title at the time, assignees and people mentioned, so
  a to-do created internally ("Raise the rate for Cleo"), renamed and
  moved into a visible list mustn't show clients its internal past.
  Clients see an event only if it was visible then and its item is
  visible now. `record()` sets `Event.is_client_visible` from the item's
  stored visibility; an edit merges only into an event of the same
  visibility, so a visible event never takes in internal edits (title,
  people mentioned) and stays visible once it was. Events from before
  this change are not visible to clients (a safe default). The feed's
  "visible to clients" filter, the API's `visible_to_clients` of an
  event and the badge on feed entries mean the same. Notifications follow
  the same rule (fixed 2026-11-21): `notify()` leaves clients out of an
  internal event even if the item became visible before it ran, and
  `mails._deliverable()` (item mails and digests, so the mail entries too)
  drops a client's notification of an internal event. The feed and the API
  already filtered by `Event.visible_to()`.
- Drift is the risk: tests compare the stored value with the value
  computed from the tree after every kind of change, and a management
  command (`check_visibility`) does the same on real data, also run
  daily, mailing admins on any difference.

## Making it obvious

Like Basecamp's bright yellow:

- A badge on everything visible to clients, wherever it's listed: lists,
  to-dos, messages, docs, files, feed entries, search results, the
  chronological list.
- A banner on the page of a visible item and above every comment and edit
  form there: "Clients can see this".
- Showing to clients asks first, in a modal that says what changes (decided
  2026-11-21, `ui-round-4.md`); hiding is one click. The switch shows what changes: "Makes 12 to-dos and 34 comments visible
  to 3 clients."
- Notification mails about visible items say so in the first line.
- API and CLI output include the visibility; the agent skills tell agents
  to check it before writing.

## Login

No single sign-on as the only way in: not every client has a Google or
Microsoft account (decided 2026-11-20).

- **django-allauth** instead of Governance's `django-authlib` (decided
  2026-11-20): it covers everything below in one maintained package, above
  all passkeys. Verify the details against its current documentation.
- Everybody can log in with their email address: a one-time code by mail
  (allauth's login by code), short-lived and single-use. A code works
  when the mail is read on the phone and the app is open on the laptop,
  which a link doesn't. Invitations work the same way.
- **Passkeys** (WebAuthn, allauth's MFA module): offered after the first
  login, then the fastest way in, without a mail. The offer (decided
  2026-11-20: once, dismissable; built 2026-11-20, `biwak/accounts/passkeys.py`):
  the first page somebody opens after a login by code leads to
  `/accounts/passkey-offer/` (and on to where they wanted to go), unless
  they have a passkey or dismissed it. "Not now, don't ask again" and
  adding a passkey set `User.passkey_offer_done`, which ends the offer for
  good; leaving the page any other way means it comes back with the next
  login by code. Not for passkey or Google logins, API and htmx requests.
  Clients get it too; the behaviour, the wording and the API shapes of
  `api-cli.md` confirmed 2026-11-20.
- Everybody's address is allauth's verified primary address
  (`verify_email()`, also when it changes): allauth confirms who someone
  is before adding a passkey, and without passwords that's a code by mail,
  which it only sends to verified addresses; without one, adding a
  passkey later than five minutes after logging in answered 403 (fixed
  2026-11-20). A changed address replaces the old one (decided 2026-11-20
  after the second visibility review): the old one doesn't log in by code
  anymore and can be given to somebody else; before, it stayed verified,
  logged in, and inviting somebody with it answered 500. Migration
  `accounts.0008` deletes old addresses left behind.
- **Single sign-on per organization** (`sso.md`, built 2026-11-21,
  replacing "Google only for staff", decided 2026-11-20): each
  organization says how its people sign in: codes and passkeys, its
  identity provider (Google Workspace or Microsoft Entra ID) allowed in
  addition, or required instead. The own organization allows Google, so
  nothing changed for staff. A Google sign-in counts only with Google's
  verified address of the person and `hd` one of the organization's
  domains (Gmail addresses where single sign-on is allowed or off), a
  Microsoft one only with the organization's tenant
  (`tid`); `biwak/accounts/sso.py` decides, the adapters ask it.
- No passwords at first; add them only if somebody really needs them
  (allauth's password pages answer 404, `biwak/urls.py`).
- Sessions last weeks; people can see their sessions and log out
  everywhere.
- Links in notification mails lead to the item, through the login if
  needed, and back to the item.
- Rate limits on login codes per address and per IP (allauth has them); the response never
  says whether an address exists.
- Staff or client is a property of the person, set by admins; everybody
  can belong to an organization (`organizations.md`; shown for clients and
  partners: "Ada, Example Ltd").
