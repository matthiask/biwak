# Single sign-on per organization

The idea (2026-11-21): sign-in through the organization's identity
provider, for clients too: Google (Workspace) now, Microsoft Entra ID
prepared. SSO is safer than codes for people whose company manages their
accounts: leaving the company ends their access there. And people
managed by an IdP shouldn't get around it with a passkey or a code.

Replaces `access.md`'s "Google only for staff" (decided 2026-11-20)
once built.

**Status:** spec (2026-11-21), the questions answered the same day.
Being built (2026-11-21), see "Built".

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
- **Gmail:** people with a `gmail.com` address may use Google whatever
  their organization's setting allows otherwise (Google owns that
  mailbox: no weaker than a code), unless their organization requires
  another IdP.
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
  (`9188040d-…`). Switching back to codes keeps the provider for later.
- **Decided while building (2026-11-21, the most secure reasonable
  option, to be confirmed):**
  - The domains of an organization signing in with Google are its
    Workspace domains, they decide whose Google accounts count: only
    admins change them (also by merging into it), and it keeps at least
    one.
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
