# Access: client visibility and login

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
    don't see a limited project's content without joining.
- **Staff** with access to a project see everything in it.
- **Clients** are never covered by all-access: they see a project only
  if they're members, and in it only what
  is visible to clients.
- Visible to clients is a switch on **containers** (lists, folders) and
  on **messages, docs and files in the root folder**, and check-in
  questions. Children of a container inherit it and have no switch of
  their own. Off by default: better to show too little once.
- Comments on a visible item are visible. There are no internal comments
  on visible items (decided 2026-11-20: too easy to get wrong).
- Clients can create to-dos, comments and messages where they can see;
  what they create is visible by definition.
- Assigning a client to a to-do requires the to-do to be visible.
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
- Comments, files attached to rich text and events follow their item.
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
- The switch shows what changes: "Makes 12 to-dos and 34 comments visible
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
  login, then the fastest way in, without a mail.
- Staff can also use Google sign-in (allauth's Google provider), but it's
  never required.
- No passwords at first; add them only if somebody really needs them.
- Sessions last weeks; people can see their sessions and log out
  everywhere.
- Links in notification mails lead to the item, through the login if
  needed, and back to the item.
- Rate limits on login codes per address and per IP (allauth has them); the response never
  says whether an address exists.
- Staff or client is a property of the person, set by admins; clients
  belong to an organization (for display: "Ada, Example Ltd").
