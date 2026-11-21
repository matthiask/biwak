# Notifications: events, subscriptions, mentions, mails, replies

**Status:** events and subscriptions are built (core, 2026-11-20:
`biwak/activity/`). Stage 1 (mentions, levels, mails, digests) is built
(2026-11-20, branch `notifications`): `mentions.py`, `notify.py`,
`mails.py` and `./manage.py send_mails`, the settings pages, the API
endpoints and `biwak notifications` (CLI 0.8.0). Stage 2 (replying by
mail) is built (2026-11-20, branch `replies`): `biwak/inbound/`
(`ReplyToken` and `InboundMessage`, `tokens.py` for the `Reply-To`,
`providers.py` with Resend's adapter, `strip.py`, `receive.py`, the
webhook `/inbound/resend/`, `./manage.py receive_mail`); decisions,
differences from Resend's documentation and open questions under "Built
in stage 2". No API or CLI changes. Retention (`prune()` in
`biwak/inbound/tokens.py`, `RETENTION_DAYS = 90`, run by `fairy_tasks`) and
the "Reply to this mail to comment/answer." line (`can_reply` in the
mail templates) built 2026-11-20, branch `reply-extras`.

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

**Edits merge** (built in stage 1, `record()`): an `edited` event by the
same person on the same item within 10 minutes of the last one updates
that event's time instead of creating a new one ("once per editing
session"). The person's last `edited` event counts, even when others'
events came in between; a merged edit tells nobody again who was told
already, except people mentioned in it for the first time (proposed by
the building agent, 2026-11-20). Changing a to-do's title, notes or due
date records `edited` (`update_todo()`; assignees record `assigned`).

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
  `@Ada Lovelace`. Clients read the label for people who aren't members
  of the project (`access.md`, decided 2026-11-20 after the second
  visibility review).
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
  `GET /lists/<pk>/mentionable/?q=` for to-dos not created yet, and
  `GET /projects/<pk>/mentionable/?q=&visible=1&folder=<pk>` for new
  messages, docs and files: who will see them, from the visibility
  checkbox (`data-mentions-visible`) or the folder, which decides when
  given; clients always create what clients see), JSON:
  `[{id, name, short_name, email, available, reason}]`, at most 10.
- **Model:** `Mention(item, comment null, user, created_at)`, written by
  the operations that save texts (`create_todo`, `update_todo`,
  `add_comment`, later messages, docs and answers) via
  `mentions.update(item, text, comment=None, actor, event=None)`. It
  parses the text, ignores people who can't see the item (a mention
  typed by hand for someone without access is shown as plain text, not
  linked), and returns those **newly** mentioned, adding them to
  `event.data["mentioned"]` for `notify()`. A to-do's title and notes
  are one text. People removed from a text are forgotten, so mentioning
  them again counts as new (proposed by the building agent, confirmed
  2026-11-20). Only mentions a save adds count: those already in the
  text before were looked at when written, so a client's rejected
  mention of staff doesn't notify them when staff save the item later
  (`previous` of `update()`, decided 2026-11-21).
- **A new mention** notifies the person (on every level except
  "nothing") and subscribes them (`explicit=True`). Editing a text later
  notifies only people newly mentioned. A mention doesn't come back
  after unsubscribing unless the person is mentioned again.
- **Mail replies and the API** may write `@ada@example.org` or the
  syntax above; plain `@Ada` is resolved only when exactly one person
  who can see the item matches (stage 2 and `api-cli.md`). What clients
  write resolves and notifies the project's members only (`access.md`).

### Levels

Per person (`User.notification_level`), overridable per project and per
item (`LevelOverride(user, project null, item null, level)`, one of the
two set; the item's override wins over the project's). An item's
override also covers what's in it: the nearest override along the item
and its containers wins (proposed by the building agent, confirmed 2026-11-20):

- **Everything** (the default): everything the person is subscribed to.
- **Only what concerns me:** being assigned, being mentioned, comments on
  items they created or commented on, their to-dos completed by someone
  else ("their": assigned to them or created by them; proposed by the
  building agent, 2026-11-20).
- **Nothing:** no mails; the feed still shows everything.

Never a notification about one's own actions.

Pages: the person's level and delivery on `/accounts/notifications/`
(linked from the user menu); a project's override in the project page's
"More" menu; an item's override next to its subscribe button. The
settings page also lists the person's overrides, items only while they
can see them, projects only while they have access (an override of a
project one has left stays, unseen, and counts again on coming back,
2026-11-21). To-dos, lists, messages, docs, files and the
library's folders have the subscribe button and the override form
(`files/_sidebar.html`); a list's override is at the bottom of the list's
page, also through the API (built 2026-11-20).

### Notified by default or only when tagged

**Status:** built (2026-11-20, CLI 0.15.0; the API shapes and the choices below confirmed 2026-11-20):
`add_member()`, `invite()`, `set_notify_choice()` and `notify_choice()`
in `biwak/projects/operations.py`, the people page with
`/projects/<pk>/people/<user>/notify/`, `POST projects/ID/members/`,
`POST projects/ID/members/invite/`, `PATCH projects/ID/members/PERSON/`,
`biwak members` and `biwak member add|invite`. Tests in
`biwak/projects/test_notify_choice.py`. Built on the way: the members
list returns `notify` as `default`, `tagged` or `nothing`, and `null` for
clients about others; a client can't add or invite (403) nor change
others' choice (403, 404 for people who aren't members). The CLI has no
command to change a choice, the API and the page do.

Decided 2026-11-20: people are in a project in one of two ways, and the
project's level is that choice, not a new setting.

- **Notified by default:** the project's level is "everything". They
  get what they're subscribed to there, including messages, docs and
  files posted to everybody.
- **Only when tagged:** the project's level is "only what concerns me".
  Posting to everybody still subscribes them, but their level holds the
  mails back unless they're mentioned or assigned, or it's about their
  own things.
- **Who sets it:** whoever adds or invites someone chooses one of the
  two (default: notified by default), stored as the person's
  `LevelOverride` for the project. The person changes it later on the
  project's notification page (built). An existing override isn't
  changed when someone is added again.
- **Shown** on the project's people page next to each member ("Notified
  by default" or "Only when tagged", from their effective level for the
  project; "nothing" shows as "No mails"), visible to staff. Staff can
  change it there for others too; a client only their own.
- **Posting** a message, doc or file therefore preselects "everybody in
  the project" (decided 2026-11-20, replacing "no default"): the levels
  already keep the mails away from those who only want them when tagged.
  The API's and CLI's `notify` defaults to everybody too.
- **API and CLI:** adding and inviting take `notify` (`default` or
  `tagged`); the members list returns it. `biwak members PROJECT` shows
  it, `biwak member add|invite … [--only-tagged]`.

### Who gets told

`notify(event)` in `biwak/activity/notify.py`, called after the commit
(`transaction.on_commit`) by `record()`:

1. Candidates: subscribers of the event's item; for `created`, also
   subscribers of its parent container; plus people newly mentioned or
   assigned by this event.
2. Without the actor, inactive people, and people who can't see the
   item **now** (`Item.objects.visible_to(user)`; for everybody at once
   `who_can_see(item)`, tested against it, 2026-11-21).
3. Filtered by each person's effective level (a query for all,
   `effective_levels()`; `notify()` makes the same number of queries for
   any number of people).
4. One `Notification(user, event, created_at, sent_at null)` per person;
   at most one unsent per person and event, a constraint in the database
   (two `notify()` at once can't tell anybody twice, 2026-11-21).

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

Built in stage 1 (proposed by the building agent, confirmed 2026-11-20):

- `send_mails` checks again when sending: inactive people, people who
  can't see the item any more and people whose level is now "nothing"
  get nothing, and those notifications are deleted. A mail that fails to
  send leaves its notifications unsent for the next run.
- At most once: notifications are marked sent when the transaction
  commits, before the mail goes out; a crash in between loses those mails
  rather than sending them twice (accepted, 2026-11-21).
- A mail that fails to be built is logged and its notifications stay
  unsent; the other mails, the digests and the check-ins go out anyway
  (each part of `send_mails` on its own, like each task of
  `fairy_tasks`; 2026-11-21). Nothing left to say (reactions to a
  comment deleted since): no mail, the notifications are deleted.
- Clients aren't told where an item moved ("Ada moved it."), like the
  feed: the name may be internal.
- Attachments are links with `BASE_URL` in the HTML part and their
  download URLs in the plain text part; the download checks access.
- The unsubscribe link of a new item a person hears about through its
  container unsubscribes from the container. A `GET` of the link only
  asks (link checkers follow links), the `POST` unsubscribes; only who
  can still see the item is shown its title.
- Digests have no one-click unsubscribing (they're about many items):
  their `List-Unsubscribe` is the settings page, without
  `List-Unsubscribe-Post`. Their subject: `[Biwak] What happened on
  19. November 2026`, from `Biwak <DEFAULT_FROM_EMAIL>`; a digest of more
  than one day (after a downtime, or switching to digests) names them:
  `[Biwak] What happened from 17. November 2026 to 19. November 2026`
  (the first and the last day with notifications, 2026-11-21).
- Mails carry `Auto-Submitted: auto-generated`.
- The `@` list for clients finds only the project's members, not by
  email, and shows no addresses.

### API and CLI

- `GET/PUT /api/v1/me/notifications/` (level, delivery),
  `GET/PUT/DELETE /api/v1/projects/{id}/notifications/` and
  `/api/v1/items/{id}/notifications/` (overrides; `level` null without
  one), `GET /api/v1/items/{id}/mentionable/?q=`. Texts written through
  the API (to-dos, comments) resolve `@email` and an unambiguous `@Name`.
- `biwak notifications` shows and sets the level and delivery;
  `--project` and `--item` the overrides (`--level default` removes
  one).

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

### Built in stage 2

Resend's documentation (checked 2026-11-20) and what that changed:

- The webhook (`email.received`) carries metadata only: `data.email_id`,
  `from` (the bare address of `From`), `to`, `cc`, `subject`,
  `message_id`, attachment metadata. Signed by Svix (`svix-id`,
  `svix-timestamp`, `svix-signature`: HMAC-SHA256 of
  `id.timestamp.body` with the `whsec_` secret); we verify it ourselves
  (no Svix package), within 5 minutes like Svix's libraries.
- `GET /emails/receiving/{id}` returns `authentication: {spf, dkim,
  dmarc}`, each `pass`, `fail`, `gray`, `processing_failed` or
  `unknown`, computed by Resend's receiving servers, and
  `raw.download_url` (a signed URL, valid about an hour) for the
  original message. We parse that original message ourselves (one parser
  for the webhook and `receive_mail`) instead of the API's `headers`,
  `text`, `html` and the attachments API, whose shapes the documentation
  doesn't fully describe.
- **Differs from the spec above:** Resend doesn't report SPF alignment,
  only SPF's result for the envelope sender. So the sender check accepts
  DMARC `pass`, or DKIM `pass` (Resend: `gray` "means the message is
  unsigned or the signing domain does not match the From domain", so
  `pass` is aligned); SPF alone is never enough. A domain without DMARC
  and without DKIM (rare) can't reply. If Resend's `from` differs from
  the `From` address we parse, its results count as `unknown` (its `from`
  compared as an address, also when it comes with a name; an answer of
  its API that isn't a JSON object fails like a network error and Resend
  tries again, 2026-11-21).

Decisions made while building (proposed by the building agent,
confirmed 2026-11-20):

- **Retention:** received mails (`InboundMessage`) and reply tokens
  expired or revoked more than 90 days ago are deleted by `fairy_tasks`
  (decided 2026-11-20).
- **Saying so:** notification mails and check-in question mails that
  carry a `Reply-To` say "Reply to this mail to comment." (to answer, for
  check-ins) above the footer (decided 2026-11-20).

- **Which mails get a `Reply-To`:** notification mails about something
  commentable (to-dos, messages, docs, files, answers; not lists), and
  check-in question mails, whose reply answers that occurrence (not the
  latest). Not digests (about many items) nor check-in summaries (a reply
  isn't an answer).
- **Order of checks:** each provider ID once; auto-replies and bounces
  dropped; no known token (or another domain), dropped; more than 20
  mails per token in the last hour (all mails to the token count,
  rejected ones too), dropped without answer; then sender, authentication,
  token valid, access. Only these four get the answer.
- **Loops** also: `multipart/report` (delivery status notifications);
  `Auto-Submitted: no` isn't automatic.
- **The answer** to a rejected reply goes to the `From` address only when
  the receiving server confirmed it; otherwise to the token's person
  (never to an address that may be impersonated). It says nothing about
  the item, carries `Auto-Submitted: auto-replied` and no `Reply-To`.
- **Access** means now: active, the item in `Item.objects.visible_to()`
  (so not trashed), commentable; for check-ins asked the question
  (`can_answer()`). Replying to a question already answered changes the
  answer, like answering again in the app.
- **Stripping:** we cut at the first quote header ("On … wrote:", "Am …
  schrieb …:", also quoted by iOS, wrapped over up to three lines but
  not past a blank line or another line starting with "On"/"Am", so the
  person's own "On Friday …" right above it stays; 2026-11-21), Outlook's header block ("From:" with
  "Sent:"/"To:" below, "Von:" with "Gesendet:"/"An:"), "-----Original
  Message-----", forwarding markers and `-- `; phones' last lines ("Sent
  from my iPhone", "Von meinem iPhone gesendet", "Get Outlook for …");
  then `email-reply-parser`. Mails without a plain text part are turned
  into text, cut where clients' HTML quotes start. Signatures without a
  delimiter ("Best regards, Ada") stay.
- **Attachments:** every part with a file name, inline images included;
  larger than 25 MB left out (noted in `InboundMessage.error`), the text
  posted anyway. Their Markdown is appended to the text.
- **Nothing written** (only quotes, no attachments): nothing posted, no
  answer.
- **`receive_mail FILE.eml`** takes `--spf`, `--dkim`, `--dmarc` (default
  `unknown`): never from the file's headers.
- **Revoking:** an admin action on reply tokens in the Django admin.
- `InboundMessage` keeps the sender and status, not the mail.

Open (values and wording the spec doesn't fix):

- Whether tokens are revoked automatically (a person deactivated or
  removed from a project; access is checked anyway).
- The wording of the answer to rejected replies (four reasons, in
  `receive.py`).
- Oversized attachments silently left out: tell the person (in the
  comment or by mail)?
- Signature images (Outlook's logos) become attachments; leave out small
  inline images?

### Setting it up

Outside the app:

1. **DNS:** a receiving subdomain (e.g. `reply.example.org`) added to
   Resend as a domain with receiving enabled; its MX record as Resend
   shows it. The organization's own MX stays untouched.
2. **Resend:** a webhook to `https://<host>/inbound/resend/` for the
   event `email.received`; its signing secret. An API key that can read
   received mails (full access; a sending-only key can't).
3. **Environment:** `REPLY_DOMAIN` (the subdomain), `RESEND_API_KEY`,
   `RESEND_WEBHOOK_SECRET` (`whsec_...`). Without all three replying is
   off: no `Reply-To`, the webhook answers 404.

### Done when (stage 2)

Tests with `.eml` samples (made up, but shaped like Gmail, Outlook,
Apple Mail and phone clients, English and German): stripping, sender
check (forwarded mail, spoofed `From`, failed DMARC), visibility changed
between sending and replying, loops and rate limits, idempotent
webhooks, attachments.
