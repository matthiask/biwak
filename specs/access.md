# Access: client visibility and login

The most delicate part of the app: a bug here shows internal content to a
client. One function decides visibility, everything uses it, and the
tests are thorough. Built in the core phase; reviewed separately before
the first client gets a login.

## Who sees what

- **Staff** members of a project see everything in it.
- **Clients** see a project only if they're members, and in it only what
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

- Everybody can log in with their email address: a one-time login link by
  mail, valid for a short time and once. Optionally a passkey afterwards.
  Invitations work the same way.
- Staff can also use Google sign-in (`django-authlib`, as in Governance).
- Sessions last weeks; people can see their sessions and log out
  everywhere.
- Links in notification mails lead to the item, through the login if
  needed, and back to the item.
- Rate limits on login links per address and per IP; the response never
  says whether an address exists.
- Staff or client is a property of the person, set by admins; clients
  belong to an organization (for display: "Ada, Example Ltd").
