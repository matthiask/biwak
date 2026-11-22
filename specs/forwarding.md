# Forwarding mails into Biwak

Staff forward a mail to one address and file it afterwards as a message
or a to-do. Out of scope at first (`SPEC.md`), brought in 2026-11-22:
replying by mail already receives, checks and parses mails, and one
address avoids having to pick among many. Decided with the user
2026-11-22.

**Status:** built 2026-11-22 (branch `forwarding`): `biwak/forwarding/`
(receiving, the "Forwarded" page, filing, deleting, the 30-day cleanup in
`fairy_tasks`, the API, `biwak forwarded`), the help in
`docs/notifications.md`. Decisions made on the way are in
`decisions-to-confirm.md`.

Depends on: `notifications.md` ("Replying by mail": `biwak/inbound/`,
Resend's webhook, the sender check, stripping), `files.md`
(attachments), `todos.md`, `access.md`, `api-cli.md`, `ui.md`.

## The address

- **One address for everybody** (decided 2026-11-22):
  `inbox@<REPLY_DOMAIN>` (off without `REPLY_DOMAIN`, like replies).
  Shown on the "Forwarded" page with "Copy".
- **Whose it is:** the sender check of replies (SPF/DKIM/DMARC results
  from Resend, the `From` matching an active staff member's address,
  own staff and externals alike, decided 2026-11-22); mails failing
  it, from clients or from unknown addresses are dropped. Only a staff
  member whose address the server couldn't confirm gets a short answer
  saying why; clients and outsiders get nothing (decided 2026-11-22:
  no mails to outsiders, failing quietly is fine).
- **What's kept:** the forwarded mail's subject, the original sender,
  date and recipients when they can be read from the forward (the
  common forward formats of Outlook, Gmail, Apple Mail; else the
  forwarder's mail as it is), the text (HTML through the paste
  converter to Markdown, quoted parts kept, signatures not stripped),
  and attachments (inline images too) up to the attachment limit.

**Receiving** (`biwak/forwarding/`): `biwak.inbound.receive` hands
mails to the inbox (and without a reply token) to
`forwarding.operations.receive()`; `parse.py` reads the forward
(`find_header()`, `parse_date()`, an attached `message/rfc822` read from
its own headers), `store()` keeps a `ForwardedMail` with its
`ForwardedFile`s, the text referencing them as `forwarded:KEY` (inline
images where they were, the others below). Refused: the `InboundMessage`
says why (`wrong_sender`, `unauthenticated`), an answer to `From` when
the receiving server confirmed it, else to the staff member whose
address it claims, else none; at most 20 answers per sender and hour.
Made-up samples of each shape in `biwak/forwarding/samples/`.

## Filing

- **"Forwarded"** (`/forwarded/`, in the person menu and the palette,
  a count when something's waiting): the person's own forwarded mails,
  newest first, each with its subject, original sender and date, the
  text folded.
- **"File as message…"**: a project (combobox), category, internal
  (visible to clients only when switched later, like any message);
  the text and attachments become the message's, by the forwarder,
  with a line "Forwarded from Ada Example <ada@example.org>, 3 Dec
  2026". Posting it tells people as posting a message does.
- **"File as to-do…"**: a list or board (one combobox of the lists the
  person can add to, grouped by project), optionally a group, the
  title from the subject, the text as notes, attachments attached.
  **Lists clients see are offered too** (decided by the user
  2026-11-22: it teaches clients they could have created a to-do
  instead of mailing), marked "(clients can see this)" like "Move
  to…"; the to-do follows its list like any to-do, its text (the line
  about the original with To and Cc included) and attachments too.
  Choosing such a list shows one line under the choice saying so
  (`forwarding/file_todo.html`, `frontend/clients-note.js`), no extra
  question. Filed messages stay internal.
- **"Delete"**: gone. Filed mails leave the list; unfiled ones are kept
  30 days, then deleted by `fairy_tasks` (the page says so).
- **Built** (`biwak/forwarding/views.py`, `forwarding/list.html`): the
  page (404 for clients and while forwarding is off), the address with
  "Copy", per mail "File as message…", "File as to-do…" and "Delete"
  (asking first: it can't be restored) as modals, "Text" folding the
  recipients and the text with its images inline (the files through
  `/forwarded/<id>/files/<key>/<name>`, the forwarder's only); the
  count in the person menu (`{% forwarded_waiting %}`) and "Forwarded"
  in the palette (`palette/actions.py`). Filing (`file_as_message()`,
  `file_as_todo()`) copies the files into attachments of the project,
  puts the line about the original first (in the forwarder's language,
  with "To:" and "Cc:" lines when known) and deletes the forwarded
  mail. The message form: title (the subject), project (combobox of the
  open, not archived projects), category; the to-do form: title, one
  combobox of the active lists and their groups ("List / Group"),
  grouped by project.
- API: `GET /forwarded/`, `POST /forwarded/{id}/file/` (message or
  to-do), `DELETE`; CLI `biwak forwarded [file ID --message PROJECT |
  --todo LIST] [delete ID]`, so agents can file mails too.
  Built (`biwak/forwarding/api.py`, CLI 0.48.1): the list is paginated
  like other lists (decided 2026-11-22: adding pagination later would
  change the response's shape), each with `sender {name, email}`,
  `sent_on`, `to`, `cc`, `text` (files as `forwarded:KEY`),
  `text_html` and `files`; `file/` takes `kind` (`message`, `todo`),
  `title` (the subject when left out), `project_id` and `category_id`
  or `list_id` and `group_id`, the same choices as the page (an
  archived project or list is a 400), and answers 201
  with the item; `DELETE /forwarded/{id}/` 204. Clients 403, somebody
  else's 404, all 404 while forwarding is off. CLI: `biwak forwarded`,
  `biwak forwarded file ID --message PROJECT [--category ID] | --todo
  LIST [--group ID] [--title …]`, `biwak forwarded delete ID`.

## Decisions made while building (to confirm)

- A mail with a reply token is a reply, even when the inbox is among
  its recipients too; only mails without one reach the inbox.
- Answers to refused forwards: to `From` when the receiving server
  confirmed it, else to the staff member whose address it claims, else
  none; at most 20 per sender and hour (then dropped silently), tagged
  like refused replies in the outbox. Their wording: "Your forwarded
  mail couldn't be kept" with the reason.
- Files over 25 MB are left out with a line (like replies), inline parts
  under 20 KB (signature logos) aren't files, like replies.
- The text keeps the forwarder's own lines above the original; a mail
  forwarded as an attachment is read from its own headers.
- The original's date is a day (`sent_on`), as written in the forward;
  dates that can't be read for sure (11/12/2026) are left out, and so is
  the date in the line.
- The filed text starts with the line, "To:" and "Cc:" lines below it
  when known, on messages and to-dos alike; in the forwarder's language.
- Both forms have a title, the subject filled in; the API's `title`
  defaults to the subject.
- Filing deletes the forwarded mail (and its files, copied into the
  item's attachments); deleting asks first. Forwarded mails aren't in the
  audit log nor in the admin: the forwarder's only.
- The message form has no "Also tell…": the project is chosen in the same
  form, so posting tells those told by default only.
