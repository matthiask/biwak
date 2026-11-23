# Subscribers: adding others, and telling them now

Subscribing others, and sometimes asking them to look at the item now,
not only to hear about its next comment. The rules of subscribing
(subscribing is the switch, assigned means subscribed) are in
`notifications.md`.

**Status:** built (2026-11-21); the whole project at once
(2026-11-23).

## The modal

`activity.views.item_subscribers` (`/items/<id>/subscribers/`,
`activity/subscribers.html`, reusing the assignee picker),
`activity.operations.share()` and `subscribable_people()`; the box is
`items/_subscribers.html`.

- **Opening it:** "Manage…" in the subscribers box, "Subscribers…" in
  the "More" menu and the palette (which also reaches lists and
  check-ins, whose pages have no subscribers box); a modal, without
  JavaScript a page. For every kind with subscribers: to-dos, lists,
  messages, docs, files, folders, check-ins.
- **In it:** the subscribers, linked to their pages, with who added them
  (`Subscription.added_by`); a picker offering people not subscribed yet
  who can see the item, for clients and externals only people they may
  know (`known_to`, `subscribable_people()` is the one rule); **"Tell
  them now"**, off by default, with an optional note (one line,
  whitespace collapsed, at most 200 characters, ignored without "Tell
  them now").
- **Saving** subscribes the added people (`added_by` the person,
  overriding an earlier unsubscribing like assigning). With "Tell them
  now" it records `shared`, which tells only the people it names ("Ada
  wants you to see this: <note>" in the lantern and mail), on every
  level (decided 2026-11-22), and counts as "what concerns me". Without
  it they're subscribed quietly: no event, the feed doesn't show it.
- **Removing:** people remove only their own subscription ("Unassign
  me" posts `unassign=1` to the subscription view, `StillAssigned`).
- **Clients** may add people they may know to items they can see, like
  subscribing themselves and mentioning.
- **The feed** shows "Ada shared it with Bob" (not the note), for
  clients by the event rules (`access.md`). Subscriptions aren't in the
  item history (the audit log doesn't cover them).
- Asking once after writing a new doc uses the same picker (`files.md`,
  "Docs").

## The whole project at once

Decided with the user 2026-11-23 ("in projects with 20 people, I have to
click 20 times or more"): the people picker of the subscribers modal and
of "Also tell…" (posting a message, doc or file, and a doc's first
"Done") offers the project's people in one go, **first in the list**,
before the people (unlike teams, which come last: the point is to be
quick). Not for assigning and not for the people a check-in asks.

- **"Staff on this project"**: the active members who aren't clients
  (own staff and externals). **"Everybody on this project"**: the
  clients too, offered only while clients can see the item (at the top
  of "Also tell…", while "Visible to clients" is ticked).
- They work like teams (`teams.md`): picking one adds a pill per member
  who's offered and not in already, nothing is stored but the people;
  an entry adding nobody isn't offered, nor "Everybody" while it would
  add the same people as "Staff". The entry says how many it adds
  ("2 people"), not how many members the project has: oneself and
  those in already aren't added (decided 2026-11-23, the user: it said
  3 and added 2). Staff only (own staff and externals,
  who get the members they may know), like teams.
- `biwak/teams/picking.py` (`project_groups()`), the picker's
  `data-project-groups` (`PeopleField.offer_teams(everybody=True)`,
  `frontend/people-picker.js`). The API and CLI take IDs as before.

## API and CLI

`GET`/`POST /api/v1/items/{id}/subscribers/` (`{people: [ids], notify:
bool, note: str}`), answering `{item_id, visible_to_clients,
subscribers: [{person, added_by, created_at}]}`; people and `added_by`
the viewer may not know are left out (`added_by` null). `biwak subscriptions
add ITEM --people ID,ID [--notify] [--note TEXT]` and `biwak
subscriptions --item ITEM`, `[clients]`.
