# Notifications: events, subscriptions, mails, replies

Events and subscriptions are part of the core phase; mails, levels,
digests and replies by mail come after.

## Events

Every change worth telling anybody about writes an event: created,
completed, reopened, assigned, commented, moved, edited (once per editing
session, not per save), visibility changed, archived, trashed. Events
feed the activity feed (`feed.md`) and notifications. They store enough
to render without the item (title at the time), and they respect
visibility like the item.

## Subscriptions

- A person subscribes to an item; for containers, also to items created
  in them later (subscribing to a list means hearing about new to-dos
  even when not assigned).
- Automatic: author, assignees, people mentioned, people commenting.
- Posting a message, doc or file lets the author choose whom to notify:
  everybody in the project (the members at that moment), chosen people,
  or nobody. Those chosen are subscribed to that item.
- **Joining a project subscribes to nothing that exists already**
  (decided 2026-11-20). New members see everything in the project and its
  feed, but get mails only for what concerns them from then on and for
  new items they're notified about. Basecamp subscribes late joiners to
  every message, which floods them.
- Everybody can unsubscribe from anything, also from mail with one
  click, and subscribe others (who see who did it).
- Subscribers are shown on the item.

## Levels

A default per person, overridable per project and per item:

- **Everything** the person is subscribed to.
- **Only what concerns me**: assignments, mentions, replies to my
  comments, my to-dos completed by someone else.
- **Nothing** (the feed still shows everything).

Never a notification about one's own actions.

## Mails

- One mail per event (with a short delay so quick edits and several
  comments merge), or a daily digest, per person.
- The full content: the comment's text, the to-do with its notes, the
  message. Attachments as links.
- Sender name is the person who acted, the address the app's. Subject
  with project and item, stable per item so mail clients thread them and
  filters work.
- First line says when the item is visible to clients (`access.md`).
- Plain text and HTML; German or English per recipient.
- Sent after the transaction commits.

## Replying by mail

Commonly used, especially by clients who rarely open the app. In scope
from the start (decided 2026-11-20).

- Every notification mail has its own reply-to address with a signed
  token for the item and the recipient. A reply is posted as a comment by
  that person, if the sender address matches theirs.
- Inbound mail by provider webhook (any service posting parsed mail) or
  by polling a mailbox over IMAP; both behind one interface.
- Quoted text and signatures are stripped (e.g. `email-reply-parser`);
  attachments become attachments of the comment.
- Visibility applies: a reply to a visible item is visible, and a person
  can only reply to what they can see now (not when the mail was sent).
- Auto-replies, out-of-office and bounces are recognised and dropped.
- Replies that can't be posted get a short answer saying why.
- Check-in questions are answered the same way (`checkins.md`).

## Tests

Who gets what for each event type and level; merging and digests;
visibility changes between sending and replying; reply parsing with real
world samples (Gmail, Outlook, Apple Mail, mobile clients, different
languages).
