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
- **Subscribing without participating**: every item (and list) has a
  "Subscribe" button next to its subscribers, for following something
  without commenting or being assigned (decided 2026-11-20).
- Everybody can unsubscribe from anything, also from mail with one
  click, and subscribe others (who see who did it).
- Subscribers are shown on the item.

## Mentions

- Typing `@` in any rich text (a to-do's title and notes, comments,
  messages, docs, check-in answers) opens a list of people, filtered as
  you type (first name, last name, short name, email); Enter or a click
  inserts the mention. Keyboard only works too.
- Only people who can see the item are offered: on internal items no
  clients, in limited projects no staff outside it. Mentioning someone
  who can't see it isn't possible; the list says why a name is missing
  ("Ada can't see this list").
- Stored as a reference to the person (renaming them updates every
  mention), rendered as their name, plain `@Ada Lovelace` in mails and
  Markdown.
- A mention notifies the person, also on the "only what concerns me"
  level, and subscribes them to the item (decided 2026-11-20). Editing
  a text later notifies only people newly mentioned.
- The mail and the item both offer unsubscribing in one click; a
  mention doesn't come back after unsubscribing unless the person is
  mentioned again.
- In replies by mail and through the API, mentions are written as
  `@email@example.org` or the API's person syntax; plain `@Name` in a
  mail is resolved only when exactly one person who can see the item
  matches.

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
- Plain text and HTML; in the recipient's language once there's a
  German translation (at the end, `SPEC.md`).
- Sent after the transaction commits.

## Replying by mail

Commonly used, especially by clients who rarely open the app. In scope
from the start (decided 2026-11-20).

- **Address**: a receiving subdomain of its own (e.g.
  `reply.example.org`) with its MX at the inbound provider; the
  organization's normal mail is untouched. Every notification mail has a
  `Reply-To` of `r-<token>@` that subdomain.
- **Token**: random, about 20 lowercase characters (local parts are
  limited to 64 characters and some servers lowercase them), stored in a
  table pointing to item, recipient and sending time; revocable, expires
  after some months.
- **Providers** behind one interface, each an adapter turning what the
  provider delivers into one inbound message (sender, recipients,
  headers, text, HTML, attachments, authentication results): Brevo and
  Resend first (both offer inbound parsing to a webhook on a subdomain),
  plus reading `.eml` files from a management command for tests and
  debugging. Polling an IMAP mailbox only if needed.
  - Brevo posts the parsed mail (text, HTML, a reply already stripped of
    quotes and signature as Markdown, all headers, an rspamd spam score);
    attachments are fetched by token through its API; no raw MIME, no
    documented SPF/DKIM verdicts.
  - Resend posts only metadata (signed webhooks); body, headers, raw MIME
    and attachments are fetched through its API, with SPF, DKIM and DMARC
    results computed by its receiving servers.
  - Verify against the providers' current documentation when building.
- **Sender check**: the reply is posted as the token's recipient only if
  the `From` address is theirs and the sender's authentication passed
  (DMARC, or SPF/DKIM aligned with the `From` domain, as computed by the
  receiving server, never trusted from headers the sender could write).
  The token alone isn't enough: forwarded mails carry it.
- **Webhooks** are authenticated (the provider's signature, or a secret
  token in a header) and idempotent (providers retry; the provider's
  message id is stored).
- **Cleanup**: quoted text and signatures are stripped
  (`email-reply-parser` on our side, even when the provider offers its
  own, so the result doesn't depend on the provider); attachments become
  attachments of the comment, with a size limit.
- Visibility applies: a reply to a visible item is visible, and a person
  can only reply to what they can see now (not when the mail was sent).
- **Loops**: auto-replies, out-of-office and bounces are recognised
  (`Auto-Submitted`, `Precedence`, empty envelope sender, common
  auto-reply headers) and dropped, never answered. A rate limit per token.
- Replies that can't be posted (wrong sender, no access any more,
  expired token) get a short answer saying why, at most once per token.
- **Threading**: outgoing mails set `Message-ID`, and `In-Reply-To` and
  `References` pointing at the item's first mail, so mail clients keep one
  thread per item; `List-Unsubscribe` with one click.
- Check-in questions are answered the same way (`checkins.md`).

## Tests

Who gets what for each event type and level; merging and digests;
visibility changes between sending and replying; reply parsing with real
world samples (Gmail, Outlook, Apple Mail, mobile clients, different
languages).
