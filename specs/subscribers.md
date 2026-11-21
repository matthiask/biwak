# Subscribers: adding others, and telling them now

Today an item's page lists its subscribers with Subscribe or Unsubscribe
for oneself. `notifications.md` says everybody may subscribe others, but
the page offers no way to. And sometimes subscribing isn't enough: the
person should look at the item now, not only hear about its next comment.

**Status:** built (2026-11-21, CLI 0.28.0). Assigned means subscribed
(`activity.operations.unsubscribe()` raises `StillAssigned`; the page,
the mail link, the API and the palette use it; "Unassign me" posts
`unassign=1` to the subscription view). The modal
(`activity.views.item_subscribers`, `/items/<id>/subscribers/`,
`activity/subscribers.html`) reuses the assignee picker; "Manage…" in the
subscribers box, "Subscribers…" in the "More" menu and the palette (which
also reaches lists and check-ins, whose pages have no subscribers box).
`activity.operations.share()` subscribes (`subscribable_people()` is the
one rule for who may be added) and, with "Tell them now", records
`shared`. Decisions made on the way:
- The `shared` event is recorded only with "Tell them now"; quiet adding
  writes no event, so the feed doesn't show it (as subscribing oneself).
- `shared` tells only the people it names, never the item's other
  subscribers, and concerns them for "only what concerns me".
- The note is one line (whitespace collapsed), at most 200 characters;
  without "Tell them now" it's ignored. The feed doesn't show it.
- Adding someone who unsubscribed before overrides that (explicit, like
  assigning and mentioning). The picker offers people not subscribed yet.
- The subscribers aren't in the item history: the audit log doesn't cover
  subscriptions.
- API: `GET`/`POST /api/v1/items/{id}/subscribers/` answer
  `{item_id, visible_to_clients, subscribers: [{person, added_by,
  created_at}]}`; people and `added_by` the viewer may not know are left
  out (null for `added_by`). `biwak subscribe ITEM --people … [--notify]
  [--note]` and `biwak subscribers ITEM`.

**Changed 2026-11-21** (`ui-round-6.md`, part C): subscribing is the
switch. Subscribed means notified of everything on the item, whatever
the person's level; the item's level override and "Notifications…" in
the items' "More" menu are gone (lists keep theirs). The subscribers box
("You're subscribed / Subscribe") is the one setting per item;
`shared` still goes through `notify()` like a mention (every level
except "nothing").

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`; visibility needs tests through every entry point.

**Depends on:** `ui-round-2.md` part B merged (names link to the person's
page, in `items/_subscribers.html`), the modals (`ui-round-1.md`), the
lantern.

**Touches:**
- `items/_subscribers.html` and a modal view (`biwak/activity/` or
  `biwak/items/`);
- `activity/operations.py` (subscribing others, the new event),
  `notify.py`, `mails.describe()`, the lantern's lines;
- the API and CLI.

## Assigned means subscribed

Decided 2026-11-21. The rule is in `notifications.md`; this part builds
it.

- **On the page:** while someone is assigned to a to-do, they can't
  unsubscribe from it. Their subscribers box says "You're assigned, so
  you hear about it" and offers "Unassign me".
- **Elsewhere:** the mail's one-click link does nothing and its page
  explains why. The API answers 400.
- **One check** in the operations, used everywhere.

## The subscribers modal

- **Opening it:** the subscribers box keeps its list and the person's own
  Subscribe or Unsubscribe. A "Manage…" link opens a modal (`data-modal`;
  without JavaScript a page).
- **In the modal:**
  - the current subscribers, linked to their pages, with who added them
    (`Subscription.added_by`);
  - a picker to add people, with pills like the assignee picker, as one
    include. It offers only people who can see the item, and for clients
    and partners only people they may know (`known_to`), as everywhere.
  - **"Tell them now"**, a checkbox, off by default, with an optional
    short note (one line, at most 200 characters).
- **Saving** subscribes the added people (`added_by` the person).
  - With "Tell them now", each of them gets a notification at once: a
    new event action, `shared`, recorded on the item.
  - The lantern and mail say "Ada wants you to see this: <note>". It
    goes through `notify()` like a mention: every level except
    "nothing" lets it through (they're subscribed anyway), and their
    mail setting decides about mail.
  - Without it, they're subscribed quietly, as today.
- **Removing:** people remove only their own subscription, as now. The
  modal doesn't unsubscribe others.
- **For every item kind** with subscribers: to-dos, lists, messages,
  docs, files, folders, check-ins.
- **Clients** may add people too, those they may know, to items they
  can see. That's consistent with subscribing oneself and with mentions.
  Visibility switches stay staff only.
- **The feed** shows "Ada shared it with Bob" for staff. For clients it
  follows the event visibility rules (`access.md`).

## API and CLI

- `POST /api/v1/items/{id}/subscribers/` with `{people: [ids], notify:
  bool, note: str}`.
- `GET` lists the subscribers with `added_by`.
- `biwak subscribe ITEM --people ID,ID [--notify] [--note TEXT]` and
  `biwak subscribers ITEM`, marked `[clients]`. Bump the CLI.

## Done when

- **Django tests:**
  - assigned means subscribed, through the page, the mail link and the
    API;
  - the modal as staff, partner and client, including a client not
    offered people they don't know, and a 404 for an internal item;
  - adding people quietly, and with "Tell them now": the notification,
    the lantern's line, the mail;
  - the feed entry for staff and clients.
- **A browser test:** the modal, the picker, saving with "Tell them now".
- **The spec's Status line** says what was built.
