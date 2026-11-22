# Public links: sharing one item outside

A link that shows one item to people without an account, read only,
for a few days. Like Basecamp's public links, but the modal first offers
the item's own link, because people with an account never need a public
one. Decided with the user 2026-11-22.

**Status:** built 2026-11-22 (branch `public-links`): `biwak/public_links/`
(model, operations, views, API), Share… in `items/_more_entries.html`
and in the palette, the CLI's `share`, `unshare` and
`public-links`; the decisions made on the way are in "Built" below and
in `decisions-to-confirm.md`.

Depends on: `access.md` (visibility, sign-in), `core.md` (items),
`files.md` (attachments, file downloads), `notifications.md` (events),
`ui.md` (modals, the danger button), `todos.md` (the calendar feed's
secret URL, the model to copy).

## What can be shared

- **Leaves only:** to-dos, messages, docs and files. Not lists or
  folders: a container would show whatever is added to it later. Not
  check-in answers either (decided 2026-11-22): they have no page and
  no "More" menu of their own.
- **By staff, on any item they see** (internal or visible to clients):
  the second, destructive button is the safeguard. Clients can't create
  public links, like the visibility switches (`access.md`).

## The modal

"Share…" in the item's "More" menu (`items/_more.html`), in the palette
(`biwak/palette/actions.py`) and as a page, like every modal form
(`form_response()`):

1. First the item's **own link** with "Copy" (`data-copy`, like the
   calendar feed), saying that people with an account open that one and
   don't need a public link: a public link is only for people outside.
2. Below, the **expiry** (1, 3, 7 or 30 days; default 7; nothing longer)
   and **"Create public link"** as the destructive button
   (`destructive=`). The own link stays the one primary thing.
3. **While a link is live** the modal shows it instead, with "Copy",
   when it expires and "Stop sharing". **One live link per item:**
   creating a new one (choosing an expiry again) replaces it.

## The badge

While a link is live, staff see a **"Public link"** badge on the item's
own page, next to its title and the client badge, opening the "Share…"
modal (`data-modal`); its title says until when. Only on the item's
page, not on rows or tiles; never for clients (decided 2026-11-22).
`{% public_link_badge item %}`, colored by `--wb-public-bg` and
`--wb-public-ink` (the lake palette's tint).

## All public links

A central page listing the live links, each with "Stop sharing" right
there (asked 2026-11-22), so nothing stays shared unnoticed.

- `/public-links/`: the item (linked, with its kind and project), who
  created the link, when it expires, "Copy" and "Stop sharing" (POST,
  no question: stopping is safe; the row goes away with htmx). Soonest
  expiry first; an empty state when nothing is shared.
- **Staff only** (decided 2026-11-22): staff see the links in the
  projects they can open (`Project.objects.accessible_to()`: all-access
  ones and those they're members of), admins see all of them. Clients
  get 404.
- Reached from the account menu and the palette ("Public links"),
  and from the "Share…" modal ("All public links").
- The API lists them too (`GET /public-links/`); the CLI
  `biwak public-links`.

## The public page

- `/p/<token>/`, no sign-in, read only, `noindex` and no referrer
  sent on.
- **Little context:** the title, the text (Markdown rendered, ticking
  off), its attachments, the file itself for files, the author's name
  and the date of the last change (`updated_at`, decided 2026-11-22). No comments, no project name, no other people, no
  navigation, no links into the app; links to other items in the text
  stay as they are (they need an account).
- **Attachments and the file download** through the token
  (`/p/<token>/…`), never by opening the app's protected URLs.
- **Gone is 404**, the same page whether the token never existed,
  expired or was stopped.

## When a link ends

- At its expiry; "Stop sharing"; replacing it.
- **Trashing the item** (or its container, or the project) or
  **archiving its project** ends it for good (decided 2026-11-22):
  those operations delete the item's links, so restoring or unarchiving
  doesn't bring them back. The page checks the item's status on every
  request too.
- `fairy_tasks` deletes expired links daily.

## Model and rules

- `PublicLink(item, token, created_by, created_at, expires_at)`; one per
  item (unique). The token is secret, `secrets.token_urlsafe(32)`,
  stored as is (it's shown again in the modal, like the calendar
  feed's), not in the audit log.
- **Operations** `create_public_link(item, days, actor)` and
  `stop_public_link(item, actor)` in `biwak/items/operations.py` (or an
  app of their own), recording an event (`shared_publicly`,
  `stopped_sharing`) so the feed says who shared what until when. They
  notify nobody: no mails, no lantern (decided 2026-11-22). **Staff
  only** (decided 2026-11-22): clients don't see them, also on items
  visible to them. The item's History (the audit log) doesn't show
  sharing, the feed does (decided 2026-11-22).
- **Visibility:** the public page shows exactly one item and what's
  inside its text; nothing pointing elsewhere is reachable through the
  token. Tests through every entry point (`AGENTS.md`).
- **API and CLI:** create, show and stop a public link (staff);
  `biwak share ITEM --days 7`, `biwak unshare ITEM`.
- **Help:** a short section where sharing belongs, saying public links
  are for people outside and expire.

## Built

Where it lives and the choices made while building (2026-11-22):

- **Code:** `biwak/public_links/` (`PublicLink`, `operations.py` with
  `create_public_link()`, `stop_public_link()`, `end_links()` called by
  `items.operations.trash()` and `projects.operations.archive_project()`,
  `delete_expired()` in `fairy_tasks`); `Item.is_shareable`
  (`SHAREABLE` in `biwak/items/models.py`, not drafts). The events
  `shared_publicly` (with `days` and `expires_at`) and `stopped_sharing`
  are in `notify.SILENT` and `activity.operations.STAFF_ONLY` (recorded
  as internal, so the feeds, the API and live updates leave them out for
  clients, and the feed's action filter doesn't offer them); the feed says "shared … publicly until …" and
  "stopped sharing … publicly". Ending a link by trashing, archiving or
  expiring records no event of its own.
- **The modal** (`public_links/share.html`, `item_share`): the own link's
  Copy is the primary button; with a live link the expiry form stays
  below it, its button still "Create public link", with "A new public
  link replaces this one." (decided 2026-11-22). Creating or
  stopping in the modal answers with the modal again (the new link
  focused) instead of a redirect, so it can be copied (decided
  2026-11-22); the page
  redirects to itself. "Stop sharing" posts `stop` to the same URL.
  `modal.js` compares all of a dialog's forms for Escape.
- **Refusals:** clients get 403 for what they see and 404 for internal
  items (the pages and the API); containers 404 on the page, 400 in the
  API. Admins stop links in projects they can't open from the page of
  all public links (they see them there), not through the item (decided
  2026-11-22).
- **Deactivating** the person who created a link keeps it, unlike their
  calendar link: the link is the item's, it expires within 30 days and
  shows on the page of all public links with their name (decided
  2026-11-22).
- **The public page** (`public_links/public.html`, not `base.html`: the
  same whether signed in or not, no scripts of the app's own beyond the
  bundle) shows the title and mentions as written (nobody looked up),
  the creator's name and the date of the last change, the text with disabled
  checkboxes (a doc's without its title line), the file's preview,
  name, size and download for files (confirmed 2026-11-22). `noindex` and `no-referrer` as meta tags and
  headers (`X-Robots-Tag`, `Referrer-Policy`), `no-store`.
  `PublicLink.objects.open()` checks expiry, the item's status, drafts
  and the project's archive on every request; the downloads
  (`/p/<token>/download/`, `/preview/`, `/attachments/<key>/<name>`)
  serve the current version and the item's own attachments only.
- **API:** `GET /public-links/`, `GET`, `POST` (`{"days": 7}`) and
  `DELETE` `items/{id}/public-link/` (404 without a live link); CLI 0.43.0.
