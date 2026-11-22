# Forwarding mails into Biwak

Staff forward a mail to one address and file it afterwards as a message
or a to-do. Out of scope at first (`SPEC.md`), brought in 2026-11-22:
replying by mail already receives, checks and parses mails, and one
address avoids having to pick among many. Decided with the user
2026-11-22.

**Status:** open.

Depends on: `notifications.md` ("Replying by mail": `biwak/inbound/`,
Resend's webhook, the sender check, stripping), `files.md`
(attachments), `todos.md`, `access.md`, `api-cli.md`, `ui.md`.

## The address

- **One address for everybody** (decided 2026-11-22):
  `inbox@<REPLY_DOMAIN>` (off without `REPLY_DOMAIN`, like replies).
  Shown on the "Forwarded" page with "Copy".
- **Whose it is:** the sender check of replies (SPF/DKIM/DMARC results
  from Resend, the `From` matching an active staff member's address);
  mails failing it, from clients, externals' too (proposed: staff
  only, externals included; question for building), or from unknown
  addresses are dropped with a short reply like refused replies.
- **What's kept:** the forwarded mail's subject, the original sender,
  date and recipients when they can be read from the forward (the
  common forward formats of Outlook, Gmail, Apple Mail; else the
  forwarder's mail as it is), the text (HTML through the paste
  converter to Markdown, quoted parts kept, signatures not stripped),
  and attachments (inline images too) up to the attachment limit.

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
- **"Delete"**: gone. Filed mails leave the list; unfiled ones are kept
  30 days, then deleted by `fairy_tasks` (the page says so).
- API: `GET /forwarded/`, `POST /forwarded/{id}/file/` (message or
  to-do), `DELETE`; CLI `biwak forwarded [file ID --message PROJECT |
  --todo LIST] [delete ID]`, so agents can file mails too.

## Done when

- A forward from a staff member's address passing the sender check
  lands in their "Forwarded" list with the original's subject, sender,
  date, text and attachments; others are refused (tests with the
  recorded shapes of Outlook, Gmail and Apple Mail forwards, made up).
- Filing makes an internal message or a to-do with everything, through
  the page, the API and the CLI; deleting and the 30-day cleanup work.
- Visibility: a filed mail is internal; nothing in "Forwarded" is
  visible to anybody but its forwarder.
- Help and the German catalog updated.
