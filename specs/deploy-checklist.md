# Deploy checklist (written 2026-11-21)

Production runs `b67e7e2` (argocd `biwak-feinheit-app/values.yaml`,
`version:`). This lists what the next deploy brings, what to set up
before or after it, and what to check. Delete or rewrite it after the
deploy.

## What's new since b67e7e2

- **Home and to-dos:** "New project" off Home; the to-dos page shows mine
  by default (`assignee=anybody` for everybody's), "Nobody active", "Assigned
  to me", "Reset filters" only with a filter, URLs without empty values.
- **Celebrations** and **installable as an app** (manifest, icons).
- **The to-do page:** the Complete toggle in the header, the timeline
  (comments with what happened between them); completing and reopening
  back and forth leaves only the net change.
- **Mail through an outbox** (`mail-sending.md`), Resend as the transport
  when switched on; bounces mark addresses undeliverable.
- **Archiving** lists from their menus; only lists can be archived.
- **UI round 6:** the combobox, inviting several people, invitations
  visible, subscribing is the switch, check-ins answered by anybody who
  sees them.
- **Sign-in per organization** (`sso.md`): codes and passkeys, SSO allowed
  or required, Google Workspace, Microsoft Entra ID.
- When merged: partners see everybody in their projects, the people page
  grouped by organization, partner organizations admin-only
  (`organizations.md`); activating and deactivating people
  (`activation.md`).
- Tests: parallel, no coverage in CI.

## Migrations (run by the PreSync job)

Schema: `accounts.0015` (`mail_undeliverable_at`), `accounts.0016`
(`invited_by`, `invited_at`), `activity.0014` (the `unassigned` action),
`organizations.0004` (the sign-in setting), `outbox.0001`.

Data, with effects to know:

- `items.0011_archived_lists_only`: archived to-dos become completed (at
  their last change, nobody as the completer), other archived items
  (not lists) active again.
- `activity.0015_only_lists_have_levels`: notification levels on single
  items are deleted (subscribing is the switch now).
- `organizations.0005_own_organization_google`: the own organization
  gets "SSO allowed, Google" and, if it had no domains, the domains of
  its active staff's addresses. **The migration prints them: read the
  PreSync job's log.**

## Before deploying

1. **`REPLY_DOMAIN`:** the deployment's secret has `RESEND_DOMAIN`, but
   the app reads `REPLY_DOMAIN` (`biwak/settings.py`): replying to
   notification mails is off in production today. Add `REPLY_DOMAIN`
   (the domain Resend receives for), or say if it's off on purpose.
2. **`ADMINS`:** not set. Given-up mails, `check_visibility` and
   errors mail the admins; set it (e.g. `[["Name", "address"]]`, the
   format `env()` reads) or accept that nobody gets those mails
   (Sentry still gets the errors).
3. **Google:** add the `openid` scope to the OAuth consent screen (next
   to `email`, `profile`); "External" if clients' Workspaces will sign
   in. Redirect URI unchanged:
   `https://biwak.feinheit.app/accounts/google/login/callback/`.
4. **Microsoft** (already in the secret): the app registration's client
   ID is the application's GUID, the secret the secret's **Value**;
   redirect URI `https://biwak.feinheit.app/accounts/microsoft/login/callback/`
   (Web, multitenant). Rotate the secret that was pasted into a chat.
5. **Mail through Resend: optional for this deploy.** Without changes
   the outbox sends through today's `EMAIL_URL` (postfix). To switch:
   - verify `biwak.feinheit.app` as a sending domain at Resend (SPF,
     DKIM, the bounce MX records it shows) and add
     `_dmarc.biwak.feinheit.app` (`p=none` to start);
   - add `email.delivered`, `email.bounced`, `email.complained` to the
     webhook at `https://biwak.feinheit.app/inbound/resend/` (same
     secret);
   - set `EMAIL_URL=resend:` and `DEFAULT_FROM_EMAIL=biwak@biwak.feinheit.app`;
   - check the account's rate limit (requests per second).
   Rolling back is setting `EMAIL_URL` back; what's in the outbox goes
   out through it.

No new cron jobs: `send_mails` retries the outbox, `fairy_tasks` prunes
it. New dependency: `django-anymail` (in the image).

## Deploying

`cd ~/projects/argocd && fl deploy biwak-feinheit-app ~/projects/sites/biwak`
once CI is green on `main`; the rollout takes about a minute.

## After deploying

- The PreSync log: the own organization's domains as printed; fix them
  on its page ("Sign-in…") if a private domain slipped in.
- Sign in with Google as staff (the `hd` check against those domains)
  and with a code.
- Send yourself a mail (a login code); with Resend, look at the headers
  (SPF, DKIM, DMARC pass) and the outbox row in the admin.
- Websockets: a doc edited live and the lantern updating (no reconnects
  every few seconds).
- Imported people: activate whom you want in (`biwak people --inactive`,
  `biwak people activate ID… --mail`) once `activation` is merged.
