# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Forwarding (`forwarding.md`, 2026-11-22)

- **Replies first:** a mail with a reply token is a reply even when the
  inbox is among its recipients.
- **Refused forwards** are answered to `From` when the receiving server
  confirmed it, else to the staff member whose address it claims, else
  not at all; at most 20 answers per sender and hour. The answer:
  "Your forwarded mail couldn't be kept" and "Forwarded mails are only
  kept when they come from the address of a staff member." or the
  authentication reason of replies.
- **Limits like replies:** files over 25 MB left out with a line,
  inline parts under 20 KB (logos) dropped.
- **The text** keeps the forwarder's own lines above the original;
  the original's date is a day as written (left out when ambiguous).
- **The filed text** starts with "Forwarded from Dora Example
  <dora@example.com>, 20 Nov 2026" and "To:" and "Cc:" lines, on
  to-dos too, in the forwarder's language.
- **The forms** have a title (the subject filled in); the message form
  has no "Also tell…" (the project is chosen in it).
- **Filing deletes** the forwarded mail; "Delete" asks first ("It can't
  be restored."). Not in the audit log, not in the admin.
- **The API's list** is complete, not paginated (kept 30 days at most).
