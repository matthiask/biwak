# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Public links (`public-links.md`, 2026-11-22)

- **Clients see the events** of items visible to them, like every
  event (`record()`): "Ada shared … publicly until …" in their feed.
  Hiding them from clients would be a special case.
- **The item's history** (audit log) doesn't show sharing, since the
  table isn't audited (the secret); the feed does.
- **Deactivating** the person who created a link keeps it (unlike their
  calendar link): the link is the item's, it expires within 30 days and
  shows on the page of all public links with their name.
- **Replacing in the modal:** with a live link the expiry form stays
  below it, its button still "Create public link", with "A new public
  link replaces this one."
- **The public page** shows for files the preview, the name and the
  size.
