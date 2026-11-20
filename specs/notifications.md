# Notifications: events, subscriptions, mentions, mails, replies

**Status:** events and subscriptions are built (core, 2026-11-20:
`biwak/activity/`). Stage 1 (mentions, levels, mails, digests) and
stage 2 (replying by mail) are open.

**Agent:** a strong model for both stages. Stage 1 decides who gets
told about what, across visibility; stage 2 posts mail as people.

## Events (built)

Every change worth telling anybody about writes an `Event`
(`biwak.activity.operations.record`): created, completed, reopened,
assigned, commented, moved, edited, visibility changed, archived,
trashed, restored, and project events (joined, added, removed). Events
store enough to render without the item (the title at the time, in
`data`) and respect visibility like their item (`Event.objects
.visible_to()`). Events feed the activity feed (`feed.md`) and
notifications.

To add in stage 1: **edits merge**. An `edited` event by the same person
on the same item within 10 minutes of the last one updates that event's
time instead of creating a new one ("once per editing session").

## Subscriptions (built)

- A person subscribes to an item; for containers, also to items created
  in them later (subscribing to a list means hearing about new to-dos
  even when not assigned).
- Automatic: author, assignees, people mentioned, people commenting.
  Automatic subscriptions respect an earlier unsubscribing
  (`Unsubscription`); being assigned or mentioned, or subscribing
  oneself, overrides it (`subscribe(..., explicit=True)`).
- **Joining a project subscribes to nothing that exists already**
  (decided 2026-11-20). Basecamp subscribes late joiners to every
  message, which floods them.
- **Subscribing without participating**: a "Subscribe" button next to
  the subscribers on every item (decided 2026-11-20).
- Everybody can unsubscribe from anything, also from mail with one click,
  and subscribe others (who see who did it, `Subscription.added_by`).
- Posting a message, doc or file lets the author choose whom to notify:
  everybody in the project (the members at that moment), chosen people,
  or nobody; those chosen are subscribed (`files.md` uses
  `notify_people()` from stage 1).

## Stage 1: mentions, levels, mails, digests

### Mentions

- **Syntax** in the stored Markdown: `[@Ada Lovelace](person:12)`, the
  same as the Basecamp CLI's, so agents know it. The label is only a
  fallback: pages and mails always show the person's current name, so
  renaming someone updates every mention. In mails and plain text:
  `@Ada Lovelace`.
- **Where:** a to-do's title and notes, comments, messages, docs,
  check-in answers: every Markdown text of an item, and comments.
- **Typing `@`** in a text field with `data-mentions="URL"` opens a list
  of people, filtered as you type (first name, last name, short name,
  email). Up/Down choose, Enter or a click inserts the syntax above,
  Escape closes. In `frontend/mentions.js`, plain JavaScript, no editor
  library.
- **Who is offered** (`mentionable_people(item)` in
  `biwak/activity/mentions.py`): active people who can see the item:
  members of the project, all staff in all-access projects, clients only
  if they're members and the item is visible to clients. People
  matching the query who can't see it are listed greyed out with the
  reason ("can't see internal items", "not a member of this project")
  and can't be chosen.
- **Endpoint** for the list: `GET /items/<pk>/mentionable/?q=` (and
  `GET /lists/<pk>/mentionable/?q=` for to-dos not created yet), JSON:
  `[{id, name, short_name, email, available, reason}]`, at most 10.
- **Model:** `Mention(item, comment null, user, created_at)`, written by
  the operations that save texts (`create_todo`, `update_todo`,
  `add_comment`, later messages, docs and answers) via
  `mentions.update(item, text, comment=None, actor)`. It parses the
  text, ignores people who can't see the item (a mention typed by hand
  for someone without access is shown as plain text, not linked), and
  returns those **newly** mentioned.
- **A new mention** notifies the person (on every level except
  "nothing") and subscribes them (`explicit=True`). Editing a text later
  notifies only people newly mentioned. A mention doesn't come back
  after unsubscribing unless the person is mentioned again.
- **Mail replies and the API** may write `@ada@example.org` or the
  syntax above; plain `@Ada` is resolved only when exactly one person
  who can see the item matches (stage 2 and `api-cli.md`).

### Levels

Per person (`User.notification_level`), overridable per project and per
item (`LevelOverride(user, project null, item null, level)`, one of the
two set; the item's override wins over the project's):

- **Everything** (the default): everything the person is subscribed to.
- **Only what concerns me:** being assigned, being mentioned, comments on
  items they created or commented on, their to-dos completed by someone
  else.
- **Nothing:** no mails; the feed still shows everything.

Never a notification about one's own actions.

Pages: the person's level and delivery on `/accounts/notifications/`
(linked from the user menu); a project's override in the project page's
"More" menu; an item's override next to its subscribe button.

### Who gets told

`notify(event)` in `biwak/activity/notify.py`, called after the commit
(`transaction.on_commit`) by `record()`:

1. Candidates: subscribers of the event's item; for `created`, also
   subscribers of its parent container; plus people newly mentioned or
   assigned by this event.
2. Without the actor, inactive people, and people who can't see the
   item **now** (`Item.objects.visible_to(user)`), checked per person.
3. Filtered by each person's effective level.
4. One `Notification(user, event, created_at, sent_at null)` per person.

Project events (joined, added, removed) notify nobody.

### Mails

- **Delivery** per person (`User.mail_delivery`): each change (the
  default) or a daily digest.
- **Each change:** `./manage.py send_mails`, run every minute by cron,
  sends one mail per person and item once the newest unsent
  notification for that item is 2 minutes old (decided 2026-11-20), so
  quick edits and several comments merge into one mail.
- **Digest:** the same command sends each digest person one mail at
  07:00 in the installation's time zone (`TIME_ZONE`) with the unsent
  notifications of the day before, grouped by project and item (decided
  2026-11-20). Nothing to say, no mail.
- **Content:** the full text: the comment, the to-do with its notes, the
  message. Attachments as links. Plain text and HTML (`templates/mails/`),
  English until the German translation.
- **Visibility line:** the first line says when the item is visible to
  clients (`access.md`).
- **Headers:**
  - `From: "Ada Lovelace (Biwak)" <DEFAULT_FROM_EMAIL>`.
  - `Subject: [Project] Item title`, the same for every mail about an
    item.
  - `Message-ID` per mail; `In-Reply-To` and `References`
    `<item-<pk>@<host>>`, so mail clients keep one thread per item.
  - `List-Unsubscribe` and `List-Unsubscribe-Post` (RFC 8058): a signed
    URL `/unsubscribe/<token>/` (no login, `django.core.signing`, person
    and item) that unsubscribes from the item.
- **Sending** through Django's mail API with `EMAIL_URL` (Resend's SMTP
  in production, decided 2026-11-20; the console in development). After
  the commit, never inside a transaction.

### API and CLI

- `GET/PUT /api/v1/me/notifications/` (level, delivery),
  `PUT/DELETE /api/v1/projects/{id}/notifications/` and
  `/api/v1/items/{id}/notifications/` (overrides),
  `GET /api/v1/items/{id}/mentionable/?q=`.
- `biwak notifications` shows and sets the level and delivery.

### Done when (stage 1)

- Mentions: parsing, rendering with current names, the `@` list with
  keyboard support, only visible people offered, only the newly
  mentioned notified, subscribing.
- `notify()` with tests per event type and level, including: a client
  isn't told about an internal item, a person who lost access isn't
  told, the actor isn't told.
- `send_mails`: merging after 2 minutes, digests at 07:00, headers and
  threading, the unsubscribe link working without login.
- Settings pages, API endpoints and the CLI command.

## Stage 2: replying by mail

Commonly used, especially by clients who rarely open the app. In scope
from the start (decided 2026-11-20).

- **Address:** a receiving subdomain of its own (e.g.
  `reply.example.org`) with its MX at Resend; the organization's normal
  mail is untouched. Every notification mail gets `Reply-To:
  r-<token>@` that subdomain.
- **Token:** `ReplyToken(token, item, user, created_at, expires_at,
  revoked_at, error_sent_at)`: random, 20 lowercase letters and digits
  (local parts are limited to 64 characters and some servers lowercase
  them), one per mail, valid 6 months (decided 2026-11-20).
- **Provider:** Resend (decided 2026-11-20) behind an interface
  (`biwak/inbound/providers.py`): an adapter turns what the provider
  delivers into one `InboundMail(sender, recipients, headers, text,
  html, attachments, spf, dkim, dmarc)`. Resend posts a signed webhook
  (Svix signatures) with metadata to `/inbound/resend/`; body, headers
  and attachments are fetched through its API, with SPF, DKIM and DMARC
  results from its receiving servers. Also `./manage.py receive_mail
  FILE.eml` for tests and debugging. Verify against Resend's current
  documentation when building. (Brevo's inbound parsing is set up
  through its API and reports no SPF/DKIM verdicts, so the sender check
  below would be ours to do.)
- **Sender check:** the reply is posted as the token's person only if
  the `From` address is theirs and the sender's authentication passed
  (DMARC pass, or SPF or DKIM pass aligned with the `From` domain, as
  the receiving server reports; never headers the sender could write).
  The token alone isn't enough: forwarded mails carry it.
- **Webhooks** are authenticated (the signature) and idempotent
  (`InboundMessage(provider, provider_id unique, received_at, status,
  error)`; providers retry).
- **Cleanup:** quoted text and signatures are stripped
  (`email-reply-parser`, on our side even when the provider offers its
  own); attachments become attachments of the comment (`files.md`,
  stage 1), at most 25 MB each.
- **Posting** goes through `add_comment()` like everything else, with
  mentions resolved as described above.
- **Visibility:** a reply to a visible item is visible; a person can only
  reply to what they can see **now**, not when the mail was sent.
- **Loops:** auto-replies, out-of-office and bounces (`Auto-Submitted`,
  `Precedence: bulk/junk/list`, an empty envelope sender,
  `X-Autoreply`, `X-Autorespond`) are dropped, never answered. At most
  20 replies per token and hour.
- **Rejections:** replies that can't be posted (wrong sender, failed
  authentication, no access any more, expired token) get a short answer
  saying why, at most once per token (`error_sent_at`).
- Check-in questions are answered the same way (`checkins.md`).

### Done when (stage 2)

Tests with `.eml` samples (made up, but shaped like Gmail, Outlook,
Apple Mail and phone clients, English and German): stripping, sender
check (forwarded mail, spoofed `From`, failed DMARC), visibility changed
between sending and replying, loops and rate limits, idempotent
webhooks, attachments.
