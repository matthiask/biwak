# Single sign-on per organization

The idea (2026-11-21): sign-in through the organization's identity
provider, for clients too: Google (Workspace) now, Microsoft Entra ID
prepared. SSO is safer than codes for people whose company manages their
accounts: leaving the company ends their access there. And people
managed by an IdP shouldn't get around it with a passkey or a code.

Replaces `access.md`'s "Google only for staff" (decided 2026-11-20).

**Status:** built (2026-11-21), see "Built" and "Threats considered";
Microsoft tested with made-up tokens only, not against a real tenant.
The choices made while building and the review's fixes confirmed
2026-11-21. Open: a further review of the claims checks and the
enforcement (see "Agent").

**Agent:** a strong model: sign-in is security-relevant; have the
claims checks and the enforcement reviewed.

**Depends on:** `organizations.md` (organizations with domains, built).

**Touches:** `biwak/organizations/` (model, admin, forms, pages),
`biwak/accounts/adapters.py`, `biwak/accounts/passkeys.py`, allauth's
settings (`SOCIALACCOUNT_PROVIDERS`: Google, Microsoft), the settings
page's sign-in card, the login page, `specs/access.md`,
`docs/` (sign-in), the CLI/API token creation.

## Sign-in per organization

Each organization has a **sign-in setting** (admins change it on the
organization's page; three levels, decided 2026-11-21):

- **Codes and passkeys** (the default, today's behaviour for clients).
- **SSO allowed:** the organization's IdP in addition to codes and
  passkeys.
- **SSO required:** only the IdP. People of the organization can't sign
  in by code and can't add or use passkeys.

With SSO, the organization says **which IdP**:
- **Google Workspace:** the organization's domains (it has them,
  `organizations.md`) are the Workspace domains; a Google sign-in counts
  only when Google's `hd` claim (the Workspace domain managing the
  account) is one of them and the address is verified. A personal
  Google account registered with a company address has no `hd`: it
  doesn't count (that's the stale-account risk).
- **Microsoft Entra ID** (prepared, built when the first organization
  needs it): the tenant ID; a sign-in counts only when the token's
  `tid` claim is that tenant. allauth's Microsoft provider.

The own organization is an organization like the others: staff's
Google sign-in today becomes the own organization's setting: SSO
allowed, Google, its Workspace domains (decided 2026-11-21: nothing
changes for staff, codes and passkeys keep working).

## Who may sign in how

- A person is matched by the verified address, as today; the
  organization is the person's (`User.organization`), not guessed from
  the domain.
- **SSO required:**
  - the login page sends people of such an organization to their IdP
    (after they enter their address, or with the provider's button);
  - codes: refused with a message naming the IdP;
  - passkeys: not offered (no passkey offer, no "Add a passkey");
    existing passkeys are removed when the organization switches to
    "required" (or a person moves into it), and signing in with one is
    refused (decided 2026-11-21: removed, not only blocked, so switching
    back, say during an IdP outage, can't revive the passkeys of people
    who left the company meanwhile; codes are the fallback then, and
    they need the company mailbox);
  - API tokens: allowed, but they expire 24 hours after creation, not
    30 days after their last use (decided 2026-11-21); tokens made
    before the switch are cut to that too;
  - sessions: end 24 hours after signing in, so the IdP is asked again
    daily, usually one click while its own session lasts (decided
    2026-11-21: there's no sync with the IdP, leaving the company
    wouldn't end a session otherwise).
- **Gmail:** people with a `gmail.com` address may use Google where
  their organization's single sign-on is allowed or off (Google owns
  that mailbox: no weaker than a code), not where it's required, also
  not where Google is required: that means its Workspace accounts only
  (decided 2026-11-21).
- **Moving people out** of an organization requiring single sign-on
  loosens how they sign in: admins only (decided 2026-11-21; other moves
  as before, `org_ops.set_organization()`, the pages and the API).
- **Merging organizations** (decided 2026-11-21, `org_ops.merge()`,
  `merge_direction()`): staff merge organizations with the same sign-in
  setting (level, provider and Microsoft's tenant). Towards a stricter
  one (a higher level, or the same level with another provider or
  tenant): admins only, after confirming a warning saying what happens to
  the merged people (passkeys removed, codes refused, tokens cut,
  sessions ended, calendar links deleted; on the page a box to tick, the
  API's `confirm`, `biwak orgs merge --confirm`, CLI 0.33.0). Towards a
  looser one: refused for everybody, change the setting first. The
  domains move with the people without the admins-only rule for domains:
  between the same settings they counted the same way already.
- **Deactivated** people can't sign in by any way (as today).

## Settings page

The sign-in card shows the connected accounts (Google, Microsoft) with
"Disconnect" (not for SSO required: the only way in), passkeys only
where allowed, and for SSO required a line saying sign-in goes through
the organization's IdP.

## Done when

- The setting per organization, admins only, with the IdP's details
  and checks (an `hd` or `tid` that doesn't match is refused with a
  message).
- Tests for each combination: codes, passkeys, Google with and
  without a matching `hd`, Gmail, a client and staff, allowed and
  required, switching to required removing passkeys, deactivated
  people; the Microsoft path at least with a faked token.
- `access.md`, the help and the admin docs say how to set it up (the
  Google and Microsoft app registrations are the user's).

## Built

- **The setting** (`biwak/organizations/`): `Organization.signin`
  (`codes`, `sso_allowed`, `sso_required`), `idp` (`google`,
  `microsoft`) and `tenant_id` (Entra ID), with database constraints
  (single sign-on has a provider, Microsoft a tenant).
  `org_ops.set_signin()` is admins only, also on the organization's page
  ("Sign-in…", a modal, `/organizations/ID/sign-in/`) and in the Django
  admin; staff see the setting on the page, the API shows it read-only
  (`signin`, `idp`; `biwak orgs show`, CLI 0.32.1). `clean_signin()`
  checks: a provider the installation has set up (`SOCIALACCOUNT_PROVIDERS`
  with a client ID), Google needs the organization's domains, Microsoft a
  tenant ID that is a UUID and not the tenant of personal accounts
  (`9188040d-…`, [Microsoft's ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference), `iss` and `tid`). Switching back to codes keeps the provider for later.
- **Decided while building (2026-11-21, the most secure reasonable
  option; confirmed 2026-11-21):**
  - The domains of an organization with single sign-on decide whose
    sign-ins count (Google's Workspace domains, the addresses Microsoft's
    tenant speaks for): only admins change them, it keeps at least one,
    and single sign-on needs them (merging: see above).
  - *Microsoft counts only for addresses of the organization's domains*:
    Entra ID doesn't verify addresses (its administrators set `mail` and
    the user principal name, the "nOAuth" problem), so a tenant matching
    `tid` could otherwise claim anybody staff moved into the
    organization. People of a Microsoft organization with addresses
    elsewhere use codes (or, where required, nothing: move them out or
    fix their address).
  - An admin requiring single sign-on for their own organization has to
    have signed in through it in this session, so nobody locks themselves
    out with a provider that doesn't work for them.
  - The setting isn't changed through the API: a token is easier to lose
    than a session, and it's an admin's rare choice.
- **The own organization** (migration `organizations.0005`, and
  `Organization.objects.own()` when it creates one): single sign-on
  allowed, Google. Without domains it gets those of its active staff's
  addresses (not free-mail domains or other organizations'): check them
  after deploying.
- **Google and Microsoft** (`biwak/accounts/sso.py`,
  `SocialAccountAdapter.pre_social_login`, which allauth calls for every
  social login after looking the person up: its callback, Google's token
  login, connecting an account): `sso.check_social()` decides. The person
  is the one allauth found by the connected account or by the address
  (`authenticate_by_email()`: Google's only when verified, Microsoft's as
  given, see below), and the provider has to vouch for exactly that
  person's address; else, and for deactivated or unknown people, it's
  refused with the same message, back on the login page. Connecting an
  account to oneself checks the same against the person signed in.
  Google's scope includes `openid`: the ID token from the code exchange
  carries `hd` and `email_verified`. Microsoft (`biwak/accounts/microsoft/`,
  allauth's provider as `provider_class`, the app registration's tenant
  `organizations`: work and school accounts only) reads the tenant from
  the ID token of the code exchange (audience, expiry, issuer naming its
  `tid`, its `oid` the same as Graph's profile) and puts it next to
  Graph's profile.
- **Matching:** by the person (`User.organization`), not the domain: an
  Acme address in the own organization counts with the own organization's
  rules.
- **Single sign-on required** (`biwak/accounts/sso.py`), where each rule
  is checked:
  - *Codes:* the login page's address and "Send me a sign-in code"
    (`ACCOUNT_FORMS`, `biwak/accounts/forms.py`) answer with the message
    naming the provider ("Acme Ltd signs in with Google.") and send the
    person to the provider's page (`signin.login`,
    `signin.request_login_code`; allauth asks to continue there, the
    address as `login_hint`); no code is sent. A code asked for before the
    switch is refused when entered: `AccountAdapter.pre_login`, which
    allauth calls for every way of signing in after recording the method,
    lets these people in only when the last method is a social login
    through the organization's provider (`sso.refuse_login()`).
  - *Passkeys:* signing in with one is refused by the same
    `pre_login`; "Add a passkey" (`/accounts/2fa/webauthn/add/`,
    `signin.add_passkey`) sends back to the settings with a message; the
    offer after a code isn't due; one added anyway is deleted at once
    (`authenticator_added`). Switching to "required", moving somebody into
    such an organization (`User.save()` on a changed organization, so the
    pages, the API, the Django admin and the importer) or merging into
    one (`merge()`, which moves people with an update) runs
    `sso.enforce_required()`: authenticators deleted, API tokens cut to 24
    hours after their creation, calendar links deleted, sessions that
    didn't sign in through the provider in the last 24 hours ended
    (`UserSession`, the session's sign-in record, see *Sessions*), except
    the current request's, which the middleware ends on the next one; open
    websockets check theirs again. It runs again after the commit
    (`enforce_required_now_and_after_commit()`, fixed 2026-11-21 after the
    review), so what other requests made meanwhile goes too; also after
    changing the domains of an organization requiring it.
  - *Sessions:* signing in through a provider keeps what counted in the
    session (`biwak_sso`, `sso.remember_sign_in()`: person, address,
    organization, provider, `hd`, `tid`, time; stored on the server).
    `sso.session_middleware` (after allauth's middleware) signs these
    people out unless that sign-in is less than 24 hours old and still
    counts with the organization as it is now (fixed 2026-11-21 after the
    review: changing the domains or the tenant, moving the person to
    another organization, even one with the same provider, or changing
    their address ends it): "Remember me", the cookie's age and
    `SESSION_SAVE_EVERY_REQUEST` don't matter, sessions without the
    record (signed in another way, before the switch) end, the API
    answers 401. Signing in sets the session's expiry to that date too
    (an absolute date, which saving on every request doesn't extend).
  - *Websockets* (the live updates and docs edited live, which accept
    edits) check `sso.session_alive()` when connecting and on their
    periodic and pushed access checks: the session exists, hasn't expired
    (Django's `exists()` ignores the expiry, fixed 2026-11-21 after the
    review), is the person's and, for these people, still counts; else
    they close.
  - *Reauthenticating* (allauth's pages confirming who somebody is before
    sensitive changes, by code or passkey) sends these people through
    their provider instead (`signin.reauthenticate()`, fixed 2026-11-21
    after the review).
  - *Addresses:* nobody changes their own address: allauth's address
    pages (`/accounts/email/`, `/accounts/confirm-email/`) answer 404 for
    everybody (fixed 2026-11-21 after the review: a Gmail address added
    there could have signed in with Google after leaving a company
    requiring single sign-on). Admins change addresses (`mail-sending.md`).
  - *API tokens:* created with `expires_at` 24 hours after `created_at`,
    using them doesn't extend that (`APIToken.objects.extend()`), and
    `for_secret()` refuses them 24 hours after their creation whatever
    `expires_at` says, so it doesn't depend on `fairy_tasks`. The API
    tokens and CLI login pages say so.
  - *Connected accounts:* no "Disconnect" (`signin.disconnect` refuses,
    the adapter's `validate_disconnect()` too).
- **The settings page's sign-in card** (`accounts/settings.html`): the
  connected Google and Microsoft accounts with their address and
  "Disconnect" (our own view: allauth's refuses the last account of
  people without passwords, here codes work; the next sign-in through the
  provider connects it again), passkeys only where allowed, and for
  "required" the line "You sign in through Acme Ltd's Google Workspace…".
- **Decided while building (2026-11-21, the most secure reasonable
  option; confirmed 2026-11-21):**
  - *Calendar links* (the iCal feed, `todos.md`) work without signing in
    and would outlast leaving the company like a passkey: none for people
    whose organization requires single sign-on (deleted on switching, the
    feed answers 404, the page says why).
  - *Sessions end 24 hours after the last sign-in through the provider*,
    and sessions without one end on the next request after switching to
    "required" (also the admin's own, who had to sign in through it
    first).
  - *A connected account counts only for the person whose address the
    provider vouches for now*: an account connected earlier whose address
    changed is refused rather than followed by its ID.
  - *The address of somebody whose organization requires single sign-on
    is told on the login page* by sending them to the provider (the spec
    asks for it, confirmed 2026-11-21); unknown and deactivated addresses
    look as before (a mail, nothing said on the page).

## Threats considered (2026-11-21)

How each is handled; the tests are in `biwak/accounts/test_sso_social.py`,
`test_sso_required.py` and `biwak/organizations/test_signin.py`.

- **An unverified address** (Google's `email_verified` false or missing,
  a string other than "true"): never matched or accepted. Microsoft's
  addresses are never verified, see the domains rule.
- **A personal Google account registered with a company address** (no
  `hd`, possibly made before the person left): doesn't count for the
  organization; only Gmail addresses count without `hd`.
- **Another Workspace** (`hd` of a lookalike, a suffix like
  `example.org.evil.example`, a subdomain, spaces, a trailing dot, a list,
  `true`): `hd` must equal one of the organization's domains, ignoring
  case only.
- **A Workspace asserting addresses of another organization:** the
  address must be the person's own, and `hd` the person's
  organization's; a Workspace issues verified addresses only of domains
  it verified.
- **Another Entra tenant, or personal Microsoft accounts:** `tid` must
  be the organization's tenant (the tenant of personal accounts can't be
  set); the app registration's endpoint is `organizations`.
- **An Entra tenant claiming any address** (`mail` and the user principal
  name are set by its administrators, "nOAuth"): counts only for
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
  the provider's ID first): it counts only when the provider vouches for
  the person's current address now.
- **allauth's "redirect" process**, which signs nobody in but updates
  the connected account, is checked like signing in (fixed 2026-11-21
  after the review).
- **Connecting an account to oneself** (allauth's connect flow) as a way
  around the rules: the same checks against the person signed in.
- **Codes for people who must use the IdP:** not sent (the address
  leads to the provider), and refused when entered (a code asked for
  before the switch), in `pre_login`, which every allauth login passes.
- **Passkeys reviving access after leaving the company:** removed on
  switching to required, moving in or merging in, refused at sign-in,
  not addable, not offered; switching back revives nothing.
- **Sessions outliving leaving the company:** 24 hours after the last
  sign-in through the provider, checked on every request from the time
  allauth stored in the server-side session; "Remember me", saving on
  every request and the cookie's age don't extend it; sessions without
  that record (codes, passkeys, before the switch, `force_login`) end;
  the session's own expiry is set to the same date for websockets; on
  switching, stored sessions that don't count are ended at once.
- **API tokens outliving it:** checked when authenticating (24 hours
  after creation, whatever `expires_at` says or `fairy_tasks` did), not
  extended by use, existing ones cut on switching.
- **Calendar links outliving it:** none for these people (see above).
- **Deactivated people:** refused by every way (allauth's `pre_login`,
  `check_social()`, Django's backend for sessions, `for_secret()` for
  tokens).
- **Locking everybody out:** single sign-on only with a provider the
  installation has set up and the organization's domains (and tenant);
  an admin requires it for their own organization only after signing in
  through it in that session, on the page and in the Django admin, which
  also keeps the domains of organizations with single sign-on (fixed
  2026-11-21 after the review); switching back to codes is always
  possible (also in the Django admin, and `./manage.py shell` as a last
  resort).
- **Staff loosening the rules:** the setting and the domains of an
  organization with single sign-on are admins only (the API shows the
  setting read-only); moving people out of an organization requiring it
  is admins only, merging into a stricter setting too, into a looser one
  refused (decided 2026-11-21).
- **Learning about addresses:** an address of an organization requiring
  single sign-on is sent to its provider with the organization's name
  (asked for by the spec, confirmed 2026-11-21); unknown and deactivated
  addresses look as before.
- **Not handled:** there is no sign-out at the provider and no sync with
  it (the 24 hours, decided). Open websockets close at their next access
  check (at most a minute, or at once when told).
- **Gmail where single sign-on is required:** refused, also where Google
  is required (decided 2026-11-21); addresses are changed by admins only,
  so none can be added to get around the provider.

## Production setup (the user's)

- Google: the existing OAuth client (`GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`) keeps working; its consent screen gets the
  `openid` scope next to `email` and `profile`, and is "External" if
  clients' Workspaces sign in too. Redirect URI
  `https://BIWAK/accounts/google/login/callback/` (unchanged).
- Microsoft (when the first organization needs it): an app registration
  for "Accounts in any organizational directory", the web redirect URI
  `https://BIWAK/accounts/microsoft/login/callback/`, a client secret;
  `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` in the deployment's
  secrets. Each organization's tenant ID goes into its setting.
- After deploying: check the own organization's domains. Migration
  `organizations.0005` fills them from its active staff's addresses if it
  had none (not free-mail domains or other organizations'), and prints
  them ("The own organization's domains for Google sign-in, from its
  staff's addresses: …"). Not guessing would end staff's Google sign-in
  on deploying (a sign-in counts only for the domains), so it guesses
  and says what (decided 2026-11-21 after the review).
