# Single sign-on per organization

Sign-in through the organization's identity provider (IdP), for clients
too: Google Workspace, and Microsoft Entra ID. Safer than codes for
people whose company manages their accounts: leaving the company ends
their access there, and people managed by an IdP mustn't get around it
with a passkey or a code. Sign-in in general is in `access.md`, second
factors in `two-factor.md`.

**Status:** built (2026-11-21). Microsoft is tested with made-up tokens
only, not against a real tenant. Open: a further review of the claims
checks and the enforcement.

## The setting (decided 2026-11-21)

Each organization has a sign-in setting, changed by admins only (the
organization's page, "Sign-in…", a modal at `/organizations/ID/sign-in/`,
and the Django admin; not through the API, a token being easier to lose
than a session; staff see it, the API shows it read-only as `signin` and
`idp`, `biwak orgs show`):

- **Codes and passkeys** (the default).
- **SSO allowed:** the IdP in addition to codes and passkeys.
- **SSO required:** only the IdP: no codes, no passkeys, no
  authenticator apps.

With single sign-on, the provider:

- **Google Workspace:** the organization's domains (`organizations.md`)
  are the Workspace domains; a Google sign-in counts only with Google's
  verified address of the person and `hd` (the Workspace managing the
  account) one of them. A personal Google account registered with a
  company address has no `hd` and doesn't count (the stale-account risk).
- **Microsoft Entra ID:** the tenant ID; a sign-in counts only when the
  ID token's `tid` is that tenant, and only for addresses of the
  organization's domains: Entra ID doesn't verify addresses (its
  administrators set `mail` and the user principal name, the "nOAuth"
  problem), so a tenant could otherwise claim anybody staff moved into
  the organization. People of a Microsoft organization with addresses
  elsewhere use codes (or, where required, nothing: move them out or fix
  their address).

`Organization.signin` (`codes`, `sso_allowed`, `sso_required`), `idp`
(`google`, `microsoft`) and `tenant_id`, with database constraints
(single sign-on has a provider, Microsoft a tenant). `org_ops.set_signin()`
and `clean_signin()` check: a provider the installation has set up
(`SOCIALACCOUNT_PROVIDERS` with a client ID), Google needs the
organization's domains, Microsoft a tenant ID that is a UUID and not the
tenant of personal accounts (`9188040d-…`, see [Microsoft's ID token
claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference),
`iss` and `tid`). Switching back to codes keeps the provider for later.

**The own organization** is an organization like the others: single
sign-on allowed, Google (`Organization.objects.own()` when it creates
one), so codes and passkeys keep working for staff.

## Rules (decided 2026-11-21)

- **Matching** is by the person: the verified address finds them, and
  the organization is theirs (`User.organization`), not guessed from the
  domain. An Acme address in the own organization counts with the own
  organization's rules.
- **A connected account counts only for the person whose address the
  provider vouches for now:** an account connected earlier whose address
  changed is refused, not followed by its ID.
- **Gmail:** `gmail.com` addresses may use Google where their
  organization's single sign-on is allowed or off (Google owns that
  mailbox: no weaker than a code), not where it's required, also not
  where Google is required: that means its Workspace accounts only.
- **The domains** of an organization with single sign-on decide whose
  sign-ins count: only admins change them, at least one stays, and single
  sign-on needs them.
- **SSO required:**
  - the login page sends people of such an organization to their IdP
    (after they enter their address, or with the provider's button);
    codes are refused with a message naming the IdP ("Acme Ltd signs in
    with Google.");
  - passkeys and authenticator apps aren't offered (no passkey offer, no
    "Add a passkey", no "Authenticator app"); existing ones are removed
    when the organization switches to "required" or a person moves into
    it, and signing in with one is refused. Removed, not only blocked, so
    switching back, say during an IdP outage, can't revive the passkeys
    of people who left the company meanwhile; codes are the fallback
    then, and they need the company mailbox;
  - sessions end 24 hours after the last sign-in through the provider,
    so the IdP is asked again daily, usually one click while its own
    session lasts: there's no sync with the IdP, leaving the company
    wouldn't end a session otherwise. Sessions without such a sign-in
    end on the next request after switching (also the admin's own, who
    had to sign in through it first);
  - API tokens are allowed but expire 24 hours after creation, not 30
    days after their last use; tokens made before the switch are cut to
    that too;
  - calendar links (the iCal feed, `todos.md`) work without signing in
    and would outlast leaving the company: none for these people
    (deleted on switching, the feed answers 404, the page says why);
  - connected accounts can't be disconnected (the only way in).
- **An admin requiring single sign-on for their own organization** must
  have signed in through it in this session, so nobody locks themselves
  out with a provider that doesn't work for them.
- **Moving people out** of an organization requiring single sign-on
  loosens how they sign in: admins only (other moves as before,
  `org_ops.set_organization()`, the pages and the API).
- **Merging organizations** (`org_ops.merge()`, `merge_direction()`):
  staff merge organizations with the same sign-in setting (level,
  provider and tenant). Towards a stricter one (a higher level, or the
  same level with another provider or tenant): admins only, after
  confirming a warning saying what happens to the merged people
  (passkeys removed, codes refused, tokens cut, sessions ended, calendar
  links deleted; a box to tick on the page, the API's `confirm`, `biwak
  orgs merge --confirm`). Towards a looser one: refused for everybody,
  change the setting first. The domains move with the people without the
  admins-only rule for domains: between the same settings they counted
  the same way already.
- **Nobody changes their own address:** allauth's address pages
  (`/accounts/email/`, `/accounts/confirm-email/`) answer 404 for
  everybody, since a Gmail address added there could sign in with Google
  after leaving a company requiring single sign-on. Admins change
  addresses (`mail-sending.md`).
- **The login page tells** that an address belongs to an organization
  requiring single sign-on, by sending it to the provider with the
  organization's name (confirmed 2026-11-21); unknown and deactivated
  addresses look as before (a mail, nothing said on the page).
- **Deactivated** people can't sign in by any way.

## Where it's enforced

- **Google and Microsoft** (`biwak/accounts/sso.py`):
  `SocialAccountAdapter.pre_social_login`, which allauth calls for every
  social login after looking the person up (its callback, Google's token
  login, connecting an account, the "redirect" process), asks
  `sso.check_social()`. The person is the one allauth found by the
  connected account or by the address (`authenticate_by_email()`:
  Google's only when verified, Microsoft's as given, see the domains
  rule), and the provider has to vouch for exactly that person's address;
  else, and for deactivated or unknown people, it's refused with the same
  message, back on the login page. Connecting an account to oneself is
  checked the same against the person signed in. Google's scope includes
  `openid`: the ID token from the code exchange carries `hd` and
  `email_verified`. Microsoft (`biwak/accounts/microsoft/`, allauth's
  provider as `provider_class`, the app registration's tenant
  `organizations`: work and school accounts only) reads the tenant from
  the ID token of the code exchange (audience, expiry, issuer naming its
  `tid`, its `oid` the same as Graph's profile) and puts it next to
  Graph's profile.
- **Codes:** the login page's address and "Send me a sign-in code"
  (`ACCOUNT_FORMS`, `biwak/accounts/forms.py`, the views `SSOLoginView`
  and `SSORequestLoginCodeView` in `signin.py`) answer with the message
  and send the person to the provider (allauth asks to continue there,
  the address as `login_hint`); no code is sent. A code asked for before
  the switch is refused when entered: `AccountAdapter.pre_login`, which
  allauth calls for every way of signing in after recording the method,
  lets these people in only when the last method is a social login
  through the organization's provider (`sso.refuse_login()`).
- **Passkeys:** signing in with one is refused by the same `pre_login`;
  "Add a passkey" (`/accounts/2fa/webauthn/add/`, `signin.add_passkey`)
  sends back to the settings with a message; the offer isn't due; one
  added anyway is deleted at once (`passkeys.passkey_added`).
- **Switching:** switching to "required", moving somebody into such an
  organization (`User.save()` on a changed organization, so the pages,
  the API, the Django admin and the importer) or merging into one
  (`merge()`, which moves people with an update) runs
  `sso.enforce_required()`: authenticators deleted, API tokens cut to 24
  hours after their creation, calendar links deleted, sessions that
  didn't sign in through the provider in the last 24 hours ended, except
  the current request's, which the middleware ends on the next one; open
  websockets check theirs again. It runs again after the commit
  (`enforce_required_now_and_after_commit()`), so what other requests
  made meanwhile goes too; also after changing the domains of an
  organization requiring it.
- **Sessions:** signing in through a provider keeps what counted in the
  server-side session (`biwak_sso`, `sso.remember_sign_in()`: person,
  address, organization, provider, `hd`, `tid`, time).
  `sso.session_middleware` (after allauth's middleware) signs these
  people out unless that sign-in is less than 24 hours old and still
  counts with the organization as it is now (changing the domains or the
  tenant, moving the person to another organization, even one with the
  same provider, or changing their address ends it). "Remember me", the
  cookie's age and `SESSION_SAVE_EVERY_REQUEST` don't matter; sessions
  without the record end; the API answers 401. Signing in sets the
  session's expiry to that date too (an absolute date, which saving on
  every request doesn't extend).
- **Websockets** (live updates and docs edited live, which accept edits)
  check `sso.session_alive()` when connecting and on their periodic and
  pushed access checks: the session exists, hasn't expired (Django's
  `exists()` ignores the expiry), is the person's and, for these people,
  still counts; else they close.
- **Reauthenticating** (allauth's pages confirming who somebody is, by
  code or passkey) sends these people through their provider instead
  (`signin.reauthenticate()`).
- **API tokens:** created with `expires_at` 24 hours after `created_at`;
  using them doesn't extend that (`APIToken.objects.extend()`), and
  `for_secret()` refuses them 24 hours after their creation whatever
  `expires_at` says, so it doesn't depend on `fairy_tasks`. The API
  tokens and CLI login pages say so.
- **Connected accounts** (the settings' sign-in section): the connected
  Google and Microsoft accounts with their address and "Disconnect", our
  own view (`signin.disconnect`: allauth's refuses the last account of
  people without passwords, here codes work; the next sign-in through the
  provider connects it again); refused where single sign-on is required
  (`signin.disconnect` and the adapter's `validate_disconnect()`), with
  the line "You sign in through Acme Ltd's Google Workspace…" there and
  no passkeys.

## Threats considered (2026-11-21)

Tests: `biwak/accounts/test_sso_social.py`, `test_sso_required.py`,
`test_sso_review.py`, `biwak/organizations/test_signin.py` and
`test_sso_decisions.py`.

- **An unverified address** (Google's `email_verified` false, missing or
  a string other than "true"): never matched or accepted. Microsoft's
  addresses are never verified: the domains rule.
- **A personal Google account registered with a company address** (no
  `hd`, possibly made before the person left): doesn't count for the
  organization; only Gmail addresses count without `hd`.
- **Another Workspace** (`hd` of a lookalike, a suffix like
  `example.org.evil.example`, a subdomain, spaces, a trailing dot, a list,
  `true`): `hd` must equal one of the organization's domains, ignoring
  case only.
- **A Workspace asserting addresses of another organization:** the
  address must be the person's own and `hd` the person's organization's;
  a Workspace issues verified addresses only of domains it verified.
- **Another Entra tenant, or personal Microsoft accounts:** `tid` must
  be the organization's tenant (that of personal accounts can't be set);
  the app registration's endpoint is `organizations`.
- **An Entra tenant claiming any address** ("nOAuth"): counts only for
  addresses of the organization's domains, which only admins change while
  it has single sign-on.
- **A forged or replayed Microsoft ID token:** only from the code
  exchange (`did_fetch_access_token`), audience the app, not expired,
  issued by its own tenant, its `oid` Graph's profile; the TLS connection
  to the token endpoint stands in for the signature, as allauth does for
  Google.
- **Google for an address whose organization requires Microsoft** (also
  Gmail): refused with the message naming Microsoft; codes and passkeys
  too.
- **A connected account outliving its address** (allauth finds people by
  the provider's ID first): counts only when the provider vouches for
  the person's current address now.
- **allauth's "redirect" process**, which signs nobody in but updates
  the connected account: checked like signing in.
- **Connecting an account to oneself** as a way around the rules: the
  same checks against the person signed in.
- **Codes for people who must use the IdP:** not sent (the address leads
  to the provider), and refused when entered (asked for before the
  switch), in `pre_login`, which every allauth sign-in passes.
- **Passkeys reviving access after leaving the company:** removed on
  switching to required, moving in or merging in; refused at sign-in,
  not addable, not offered; switching back revives nothing.
- **Sessions outliving leaving the company:** 24 hours after the last
  sign-in through the provider, checked on every request from the record
  in the server-side session; "Remember me", saving on every request and
  the cookie's age don't extend it; sessions without the record (codes,
  passkeys, before the switch, `force_login`) end; the session's own
  expiry is the same date, for websockets; on switching, stored sessions
  that don't count end at once.
- **API tokens outliving it:** checked when authenticating (24 hours
  after creation, whatever `expires_at` says or `fairy_tasks` did), not
  extended by use, existing ones cut on switching.
- **Calendar links outliving it:** none for these people.
- **Deactivated people:** refused by every way (allauth's `pre_login`,
  `check_social()`, Django's backend for sessions, `for_secret()` for
  tokens).
- **Locking everybody out:** single sign-on only with a provider the
  installation has set up and the organization's domains (and tenant);
  an admin requires it for their own organization only after signing in
  through it in that session, on the page and in the Django admin, which
  also keeps the domains of organizations with single sign-on; switching
  back to codes is always possible (also in the Django admin, and
  `./manage.py shell` as a last resort).
- **Staff loosening the rules:** the setting and the domains of an
  organization with single sign-on are admins only (the API shows the
  setting read-only); moving people out of an organization requiring it
  is admins only, merging into a stricter setting too, into a looser one
  refused.
- **Gmail where single sign-on is required:** refused, also where Google
  is required; addresses are changed by admins only, so none can be added
  to get around the provider.
- **Learning about addresses:** an address of an organization requiring
  single sign-on is sent to its provider with the organization's name
  (decided); unknown and deactivated addresses look as before.
- **Not handled:** no sign-out at the provider and no sync with it (the
  24 hours, decided). Open websockets close at their next access check
  (at most a minute, or at once when told).

## Production setup (the user's)

- Google: the existing OAuth client (`GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`); its consent screen has the `openid` scope next
  to `email` and `profile`, and is "External" if clients' Workspaces sign
  in too. Redirect URI `https://BIWAK/accounts/google/login/callback/`.
- Microsoft (when the first organization needs it): an app registration
  for "Accounts in any organizational directory", the web redirect URI
  `https://BIWAK/accounts/microsoft/login/callback/`, a client secret;
  `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` in the deployment's
  secrets. Each organization's tenant ID goes into its setting.
- After deploying: check the own organization's domains. Migration
  `organizations.0005` fills them from its active staff's addresses if it
  had none (not free-mail domains or other organizations'), and prints
  them. Not guessing would end staff's Google sign-in on deploying (a
  sign-in counts only for the domains), so it guesses and says what
  (decided 2026-11-21 after the review).
