# Notifications: events, subscriptions, mentions, mails, replies

**Status:** built (2026-11-20, changed 2026-11-21: subscribing is the
switch). `biwak/activity/` (`operations.record()`, `mentions.py`,
`notify.py`, `mails.py`, `./manage.py send_mails`, the settings pages,
the API, `biwak notifications`); replying by mail in `biwak/inbound/`.
The lantern (notifications in the app, reading): `lantern.md`. Adding
others as subscribers: `subscribers.md`. The outbox: `mail-sending.md`.

## Events

Every change worth telling anybody about writes an `Event`
(`biwak.activity.operations.record`): created, completed, reopened,
assigned, commented, moved, edited, visibility changed, archived,
trashed, restored, pinned, shared, project events (joined, added,
removed). Events store enough to render without the item (the title at
the time, in `data`) and respect visibility like their item
(`Event.objects.visible_to()`). They feed the activity feed (`feed.md`)
and notifications.

**Edits merge:** an `edited` event by the same person on the same item
within 10 minutes of their last one updates that event's time instead of
creating a new one, even when others' events came in between; a merged
edit tells nobody again who was told already, except people mentioned in
it for the first time.

## Subscriptions

- **Subscribing is the switch** (decided 2026-11-21, like Basecamp):
  subscribed means notified of everything on the item, whatever the
  person's level; every subscription counts the same, also the automatic
  ones. Unsubscribing is how to stop hearing about one item; the
  subscribers box ("You're subscribed / Subscribe") is the one setting
  per item. Levels (below) decide who gets subscribed automatically.
- Subscribing to a container also means hearing about items created in
  it later (subscribing to a list: new to-dos, even when not assigned).
- **Automatic:** the author, assignees, people mentioned (not on
  "nothing"), people commenting. They respect an earlier unsubscribing
  (`Unsubscription`); being assigned or mentioned, being added, or
  subscribing oneself overrides it (`subscribe(..., explicit=True)`).
- **Joining a project subscribes to nothing that exists already**
  (decided 2026-11-20): Basecamp subscribes late joiners to every
  message, which floods them.
- Everybody can subscribe themselves ("Subscribe" next to the
  subscribers on every item, decided 2026-11-20), unsubscribe from
  anything, also from a mail with one click, and add others
  (`subscribers.md`).
- **Assigned means subscribed** (decided 2026-11-21): while assigned to a
  to-do, nobody can unsubscribe the person (`StillAssigned`, one check
  for the page, the mail link, the API and the CLI). The box says
  "You're assigned, so you hear about it" and offers "Unassign me"; the
  mail's link does nothing and its page says why; the API answers 400.
- **Notifications are additive** (decided 2026-11-21, replacing
  "Everybody / Only these people / Nobody"): "Report by default to those
  who want to hear about it according to their settings, and allow
  additional people to hear about it." The poster can't hide something
  new from people who want it ("if people don't want to be notified
  about files, then upload them to Google Drive or wherever"). Posting a
  message, doc or file always tells `notify.told_by_default()`: the
  subscribers of its container (folder) and the members whose level for
  it is "everything", of those who see it, never the poster; being told
  subscribes them. The poster can only add people (`also`), whatever
  their level, subscribed and told like them. `notify_people(item,
  actor=, also=)` does it for `create_message()`, `create_doc()` and
  `create_upload()` (not inside `importing()`). Mentions and
  assignments as before. API: `also` (IDs of members; multipart: comma
  separated); an older CLI's `notify` is accepted, its IDs count as
  `also`, `everybody` and `nobody` are ignored. CLI: `--also IDS`
  (0.37.0).
- **The form** (`files.common.NotifyForm`, decided 2026-11-21): no
  choice, a line saying who will be told ("Ada, Bob and 3 others will be
  told.", `told_line()`: the names the poster may know, the others
  counted; "Nobody is told unless you add people."), below it "Also
  tell…", the people picker (`PeopleField`) of the members who see it
  (in a folder as the folder says; what clients post is visible) and
  aren't told already, nothing preselected. **At the top the line
  follows "Visible to clients"** (decided 2026-11-22): staff's form
  renders the line for both (`intro_lines`) and shows the one ticked,
  and offers the clients of the project in "Also tell…" only while it's
  ticked (`frontend/told.js`: unticking takes the clients picked away);
  the server tells exactly that (`notify_people()` with the item's
  visibility). Clients picked for an internal item are a form error,
  and a 400 in the API ("Clients can't see it."). A doc begun as a
  draft asks at its first "Done" ("Tell people about it?",
  `docs.TellForm`): the same line and "Also tell…" (the project's
  members too, decided 2026-11-22) with a note; "Tell them too" records
  `shared` to those told by default
  (not subscribed yet) and those added, "No one else" to those told by
  default only; without an answer, an hour after the last change, as
  "No one else" (`files.md`, decided 2026-11-21).

## Mentions

- **Syntax** in the stored Markdown: `[@Ada](person:12)`, the Basecamp
  CLI's, so agents know it. The label is only a fallback: pages and
  mails show the person's **current short name** ("@Ada"; `people.md`,
  "Names", for people with the same first name), the full name in the
  `title`, so renaming updates old mentions. Where the reader may not
  know the person, the label as written (`mentions.visible_people()`;
  clients read the label for people who aren't members, `access.md`).
  The `@` list and `syntax()` (also for the API's and mail replies'
  `@Name`) write the short name as the label.
- **Mails and plain text** (excerpts) render mentions the same way,
  through `reader()`, so a mail uses its recipient's view; in mails and
  the API's `*_html` mentions aren't links.
- **Where:** every Markdown text of an item (a to-do's title and notes
  are one text), and comments.
- **Typing `@`** in a field with `data-mentions="URL"`
  (`frontend/mentions.js`): a list of people filtered by first, last and
  short name and email; Up/Down, Enter or a click, Escape. Endpoints:
  `GET /items/<pk>/mentionable/?q=`, `/lists/<pk>/mentionable/` for new
  to-dos, `/projects/<pk>/mentionable/?visible=1&folder=<pk>` for new
  messages, docs and files (who will see them); JSON `[{id, name,
  short_name, email, available, reason}]`, at most 10. The doc's live
  editor doesn't complete names yet (the syntax works).
- **Who is offered** (`mentionable_people(item)`): active people who can
  see the item; people matching who can't are greyed out with the reason
  ("can't see internal items", "not a member of this project"). Clients
  find only the project's members, not by email, and see no addresses.
- **Saving** (`mentions.update(item, text, comment=None, actor,
  event=None)`, called by the operations saving texts): ignores people
  who can't see the item (a hand-typed mention of them stays plain text)
  and returns those **newly** mentioned into `event.data["mentioned"]`.
  Only mentions a save adds count (`previous`, decided 2026-11-21: a
  client's rejected mention of staff doesn't notify them when staff save
  later); people removed from a text are forgotten, so mentioning them
  again is new.
- **A new mention** notifies and subscribes the person (`explicit=True`),
  except on the level "nothing" (decided 2026-11-21: there only what the
  person does subscribes them). A mention doesn't come back after
  unsubscribing unless the person is mentioned again.
- **The API and mail replies** may write `@ada@example.org`, the syntax,
  or `@Ada` when exactly one person who can see the item matches. What
  clients write resolves and notifies the project's members only.

## Levels

Per person (`User.notification_level`), overridable per **project** and
per **list** only (`LevelOverride(user, project null, item null,
level)`, the list's wins; decided 2026-11-21: other items have no level,
"Notifications…" is in lists' "More" menu only, the API answers 400 for
other items). **Folders have no level of their own, they follow the
project's** (confirmed 2026-11-21).

- **Everything** (the default): posting to everybody subscribes the
  person; subscribed to a list, they hear about every new to-do in it.
- **Only what concerns me:** posting to everybody doesn't subscribe
  them; being mentioned or assigned and their own things (creating,
  commenting) do. New to-dos in a list they follow reach them only when
  they're mentioned or assigned.
- **Nothing:** only what they do themselves (commenting, being
  assigned) subscribes them; mentions neither notify nor subscribe. The
  feed still shows everything.

Never a notification about one's own actions.

**Notified by default or only when tagged** (decided 2026-11-20): how
someone is in a project is the project's level, not a new setting.
Whoever adds or invites someone chooses "Notified by default"
("everything", the default) or "Only when tagged" ("only what concerns
me"), stored as the person's `LevelOverride` for the project
(`add_member()`, `invite()`, `set_notify_choice()`,
`notify_choice()` in `biwak/projects/operations.py`); adding someone
again doesn't change it. The project's people page shows it next to
each member ("No mails" for "nothing") to own staff; own staff change
it for others, clients and partners see and change only their own
(partners too, decided 2026-11-21 after a review:
`can_change_notify_choice()`). API: `notify` (`default`, `tagged`,
`nothing`; `null` for clients and partners about others) on the members list, adding
and inviting; `biwak members`, `biwak member add|invite …
[--only-tagged]`.

Pages: the level and delivery on `/accounts/notifications/`; a project's
override in its "More" menu, a list's in the list's. The settings page
lists the overrides, lists only while the person sees them, projects
only while they have access (an override of a project one left stays,
unseen, and counts again on coming back).

## Who gets told

`notify(event)` in `biwak/activity/notify.py`, after the commit
(`transaction.on_commit`):

1. Candidates: the item's subscribers; for `created` also its
   container's; plus people newly mentioned or assigned by the event. A
   `shared` event has only the people it names.
2. Without the actor, inactive people and people who can't see the item
   **now** (`visible_to()`; `who_can_see(item)` for everybody at once).
3. Told (`wanting()`): every subscriber of the item, whatever their
   level, and the people the event assigns; the newly mentioned and
   `shared` and reactions except on "nothing" (a new doc's "Tell people
   about it?", `posted` in the event, on every level like posting,
   decided 2026-11-22); the container's
   subscribers about a new item on "everything" (`effective_levels()`,
   the same number of queries for any number of people). Check-in
   answers: `checkins.md`.
4. One `Notification(user, event, created_at, sent_at, read_at)` per
   person, at most one unsent per person and event (a database
   constraint: two `notify()` at once can't tell anybody twice).

Project events and pinning notify nobody. Notification records are kept
(decided 2026-11-21: small rows, pruned only if the table actually grows
large).

## Mails

- **Delivery** per person (`User.mail_delivery`): each change (the
  default), a daily digest, or none (`lantern.md`). None means no mails
  at all, check-in questions and summaries included (decided
  2026-11-21, `checkins.md`); digests leave check-in mails alone.
- **Each change:** `send_mails`, every minute by cron, sends one mail
  per person and item once the newest unsent notification for it is 10
  minutes old (`MERGE_AFTER`; 2 minutes decided 2026-11-20, 10 since
  2026-11-21: "if it were urgent, they would have gotten a phone call,
  or they would have Biwak open"; the lantern is immediate), so quick
  edits merge. **A batch of
  uploaded files is one mail** (`batch_mail()`, `mails/batch.*`,
  `files.md`), whose unsubscribe link is the settings page (there's no
  one item); one person's uploads into one folder (or the top level)
  are one group, so rounds within the 10 minutes merge too (decided
  2026-11-21), chained as the lantern does (`lantern.chain()`, decided
  2026-11-22: a round more than 10 minutes after the one before is a
  mail of its own unless it's the same batch). A batch still going up
  waits: while the newest file's event says `more` follow, up to
  `BATCH_WAIT` (an hour) after it.
- **Digest:** at 07:00 in `TIME_ZONE`, the unsent notifications of the
  day before, grouped by project and item, a batch as one entry; nothing
  to say, no mail. Subject `[Biwak] What happened on 19. November 2026`
  (or "from … to …" for more than one day, the first and last day with
  notifications), from `Biwak <DEFAULT_FROM_EMAIL>`.
- **Content:** the full text (the comment, the to-do with its notes, the
  message), plain text and HTML (`templates/mails/`). Attachments are
  links (the download checks access). The first line says when the item
  is visible to clients (`access.md`). Clients aren't told where an item
  moved: the name may be internal.
- **Headers:** `From: "Ada Lovelace (Biwak)" <DEFAULT_FROM_EMAIL>`;
  `Subject: [Project] Item title`, the same for every mail about an
  item; `In-Reply-To` and `References` `<item-<pk>@<host>>` for one
  thread per item; `Auto-Submitted: auto-generated`;
  `List-Unsubscribe` and `List-Unsubscribe-Post` (RFC 8058) with a
  signed `/unsubscribe/<token>/` (no login). A `GET` of it only asks
  (link checkers), the `POST` unsubscribes; only who still sees the item
  is shown its title. Through a container, it unsubscribes from the
  container. Digests: the settings page, no one-click.
- **Completing and reopening back and forth** (decided 2026-11-21,
  replacing deleting the earlier event within ten minutes): every one is
  recorded and notifies as usual. Of a person's unsent notifications,
  those of one person's consecutive completing and reopening of an item
  are mailed as the net change (`timeline.cancelled()` in
  `mails._deliverable()`): the last one, or nothing (and they're deleted)
  when the to-do is back where it started. A completion already mailed is
  followed by a mail of the reopening, so the inbox ends up right. The
  lantern does the same with the unread ones (`lantern.md`).
- **Checked again when sending:** inactive people and people who can't
  see the item any more get nothing (their notifications are deleted),
  and read ones are left out (`lantern.md`); the level decided who was
  told, it doesn't hold mails back later. Nothing left to say, no mail.
- **Once:** notifications are marked sent in the transaction that puts
  their mail into the outbox (`mail-sending.md`); a mail failing to be
  built is logged and its notifications stay unsent, the other mails,
  digests and check-ins go out anyway.

## API and CLI

`GET/PUT /api/v1/me/notifications/` (level, delivery),
`GET/PUT/DELETE /api/v1/projects/{id}/notifications/` and
`/api/v1/items/{id}/notifications/` (lists only), `GET
/api/v1/items/{id}/mentionable/?q=`. `biwak notifications` shows and
sets the level and delivery, `--project` and `--item` the overrides
(`--level default` removes one); `biwak subscribe ITEM` and `biwak
unsubscribe ITEM` for oneself.

## Replying by mail (stage 2)

Commonly used, especially by clients who rarely open the app; in scope
from the start (decided 2026-11-20). `biwak/inbound/`: `ReplyToken`,
`InboundMessage`, `tokens.py`, `providers.py`, `strip.py`, `receive.py`,
the webhook `/inbound/resend/`, `./manage.py receive_mail`.

- **Address:** a receiving subdomain of its own (`REPLY_DOMAIN`) with
  its MX at Resend; the organization's normal mail is untouched. Every
  notification mail about something commentable (not lists, digests or
  check-in summaries) and every check-in question mail gets `Reply-To:
  r-<token>@` it and says "Reply to this mail to comment." (to answer,
  for check-ins; `can_reply`).
- **Token:** `ReplyToken(token, item, user, created_at, expires_at,
  revoked_at, error_sent_at)`, 20 lowercase letters and digits (some
  servers lowercase local parts), one per mail, valid 6 months (decided
  2026-11-20). Revoked by admins in the Django admin; not revoked
  automatically when someone is deactivated or removed from a project
  (decided 2026-11-21: access is checked on every reply anyway). A reply to a
  question mail answers that occurrence.
- **Provider:** Resend (decided 2026-11-20) behind an interface
  (`providers.py`, `InboundMail`). Its webhook (`email.received`)
  carries metadata only, signed by Svix (verified by us, no Svix
  package, within 5 minutes). `GET /emails/receiving/{id}` gives
  `authentication: {spf, dkim, dmarc}` and the raw message, which we
  parse ourselves (one parser for the webhook and `receive_mail`). An
  answer of its API that isn't a JSON object fails like a network error,
  so Resend tries again.
- **Sender check** (decided 2026-11-20): posted as the token's person
  only if `From` is theirs and DMARC or DKIM passed (Resend's `gray`
  DKIM means unsigned or not aligned, so `pass` is aligned); SPF alone
  never (Resend doesn't report its alignment), so a domain without DMARC
  and DKIM can't reply. If Resend's `from` differs from the `From` we
  parse, its results count as `unknown`. The token alone isn't enough:
  forwarded mails carry it. `receive_mail FILE.eml` takes `--spf`,
  `--dkim`, `--dmarc` (default `unknown`), never from the file.
- **Order of checks:** each provider ID once (`InboundMessage`, keeping
  sender and status, not the mail); auto-replies and bounces dropped
  (`Auto-Submitted` other than `no`, `Precedence: bulk/junk/list`, an
  empty envelope sender, `X-Autoreply`, `X-Autorespond`,
  `multipart/report`), never answered; unknown tokens dropped; more than
  20 mails per token and hour dropped; then sender, authentication,
  token valid, access. Only these four get a short answer, at most once
  per token (`error_sent_at`): to `From` only when the receiving server
  confirmed it, else to the token's person; nothing about the item,
  `Auto-Submitted: auto-replied`, no `Reply-To`.
- **Access** means now: active, the item in `visible_to()` (not
  trashed), commentable; for check-ins `can_answer()`. A reply to a
  visible item is visible. Replying to a question already answered
  changes the answer.
- **Posting** goes through `add_comment()` (or the answer), mentions
  resolved as above.
- **Stripping** (`strip.py`): cut at the first quote header ("On …
  wrote:", "Am … schrieb …:", wrapped over up to three lines but not
  past a blank line or another line starting with "On"/"Am", so the
  person's own "On Friday …" stays), Outlook's header block (English and
  German), "-----Original Message-----", forwarding markers and `-- `;
  phones' last lines; then `email-reply-parser`. HTML-only mails are
  turned into text, cut where clients' quotes start. Signatures without
  a delimiter stay. Nothing written (only quotes, no attachments):
  nothing posted, no answer.
- **Attachments** become the comment's (`files.md`): every part with a
  file name, except inline parts under 20 KB (signature logos, decided
  2026-11-21). Larger than 25 MB left out, with a line in the comment
  saying which (decided 2026-11-21; no mail back).
- **Retention:** `InboundMessage` rows and reply tokens expired or
  revoked more than 90 days ago are deleted by `fairy_tasks`
  (`tokens.prune()`, `RETENTION_DAYS`, decided 2026-11-20).

**Setting it up:** a receiving subdomain added to Resend with receiving
enabled and its MX record; a webhook to `https://<host>/inbound/resend/`
for `email.received`; an API key that can read received mails (full
access). `REPLY_DOMAIN`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`
(`whsec_...`): without all three replying is off (no `Reply-To`, the
webhook answers 404).
