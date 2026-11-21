# Passkeys as a way in, authenticator apps as an optional second factor

The trigger (2026-11-21, after deploying): once somebody had a passkey,
signing in by code or Google led to allauth's two-factor step, whose page
asks for an "authenticator code" nobody set up (passkeys counted as a
second factor).

**Status:** built (2026-11-21, CLI 0.36.0). Where each rule is enforced:

- *The two-factor step* counts only authenticator apps:
  `adapters.MFAAdapter.is_mfa_enabled()` (`MFA_ADAPTER`), which allauth's
  `AuthenticateStage` and its page ask; passkeys count only when asked
  about alone (allauth's reauthentication offering them); people whose
  organization requires SSO have no second factor there. The page is
  `signin.TwoFactorView` (`/accounts/2fa/authenticate/`,
  `mfa/authenticate.html`): the code field only, posts without a code are
  a missing code, never a passkey.
- *The settings' card* (`accounts/settings.html`, "Authenticator app"):
  `signin.activate_app` (`/accounts/2fa/totp/activate/`, a modal: QR code,
  key, the code; allauth's reauthentication first; refused for SSO
  required) and `signin.deactivate_app` (`…/deactivate/`, the app's code
  through allauth's `ReauthenticateForm`, then its `deactivate_totp`
  flow). `MFA_SUPPORTED_TYPES = ["webauthn", "totp"]`, no recovery codes,
  `MFA_TOTP_ISSUER = "Biwak"`.
- *Confirming who one is* with an app: not by a code by mail (built
  2026-11-21, the most secure reading of "the app's code once more": a
  code by mail would otherwise add a passkey, which signs in alone, or
  turn the app off): `AccountAdapter.get_reauthentication_methods()` leaves
  it out, `signin.reauthenticate(…, by_code=True)` sends the code pages
  to the app's.
- *Resets*: `activation.can_reset_two_factor()` (`can_change()`, not
  oneself), `activation.reset_two_factor()` (deletes the app, ends the
  sessions with `UserSession.end()`, `live.check_access()`, mails through
  the outbox: `accounts/two_factor_reset.txt`, `Kind.ACCOUNT`, from the
  actor, not to inactive people or bounced addresses); the page
  `/people/<id>/reset-two-factor/` (offered on the person's page and in the
  palette only when the person has an app), `POST
  /api/v1/people/{id}/reset-two-factor/` (`reset`: whether there was an
  app), `biwak people reset-two-factor ID`. Without an app nothing happens
  (no mail, sessions stay). Passkeys stay. Audited: migration
  `accounts.0017` puts `mfa_authenticator` in the audit log without
  `data` (the app's secret, the passkey's key) and `last_used_at`.
- *SSO required*: `sso.enforce_required()` already deletes every
  authenticator; `signin.activate_app` refuses, the card isn't shown,
  `passkeys.passkey_added` deletes one coming through anyway.
- *Organizations requiring a second factor* (built 2026-11-21: a switch,
  `Organization.requires_two_factor`, "Require a second factor" in the
  sign-in modal next to the levels, since it combines with "codes" and
  "SSO allowed"; `two_factor_required` is false where SSO is required):
  `two_factor.refuse_login()` from `AccountAdapter.pre_login` (fails
  closed: no record counts as a code); `two_factor.setup_required()`,
  checked on every request (`two_factor.setup_middleware`: pages redirect
  to `/accounts/two-factor/`, htmx gets `HX-Redirect`, the API with the
  session 403) and for websockets (`sso.session_alive()`); the paths
  setting one up needs stay open (`SETUP_PATHS`). A sign-in through the
  organization's IdP is recognized by the session's record
  (`sso.remember_sign_in()`: user, organization, address and the
  organization's provider), without the 24 hours of SSO required.
  Decided on the way: people with a passkey but no app who sign in by code
  are refused ("sign in with your passkey"): letting them add an app
  after a code alone would make the code enough. A person's own app is
  asked for after their organization's IdP too (as everywhere), the
  requirement only doesn't need it there.
- Tests: `biwak/accounts/test_two_factor.py` (every way in, the card,
  reauthentication), `biwak/accounts/test_two_factor_required.py`,
  `biwak/organizations/test_two_factor_reset.py`,
  `biwak/test_cli_people.py`.

Not done, open: the app's secret is stored as allauth stores it (no
encryption, `MFAAdapter.encrypt()` could add it); a reset keeps the
person's API tokens; sessions signed in by code before an organization
starts requiring a second factor stay for people who have one; merging
or moving people between organizations doesn't look at the switch (only
at the sign-in levels of `sso.md`).

**Agent:** a strong model; sign-in is security-relevant: tests for every
way in.

**Depends on:** `access.md` (codes, passkeys, the passkey offer),
`sso.md` (organizations requiring SSO), `activation.md` (who may change
whom), `mail-sending.md` (the outbox).

## Decided (2026-11-21)

- **Passkeys are a way in, not a second factor:** a code, Google (or the
  organization's IdP) and a passkey are each enough alone, as `access.md`
  describes passkeys. allauth's two-factor step never asks for a passkey.
- **Authenticator apps (TOTP) are an optional second factor:** anybody
  may turn one on in their settings (a QR code and a code to confirm, one
  app per person); then signing in by code or through Google asks for the
  app's code (the two-factor step, showing only the code field). A
  passkey sign-in stays enough alone (device plus PIN or fingerprint).
  Turning it off needs the app's code once more (allauth's
  reauthentication).
- **No recovery codes:** losing the app means signing in with a passkey,
  or asking for a reset.
- **Resetting someone's second factor:** "Reset two-factor…" on the
  person's page (a modal), the API and the CLI, with the split of
  `activation.md`: staff reset clients, admins also own staff and
  partners; nobody resets themselves this way (they turn it off in the
  settings). A reset deletes the person's authenticator app, ends their
  sessions and mails them (through the outbox: "Ada removed your
  authenticator app"), so a reset they didn't ask for is noticed. The
  audit log has it (allauth's `Authenticator` table audited).
- **Organizations requiring SSO:** no passkeys and no authenticator apps
  (the IdP does that); existing apps are deleted when the organization
  switches to "required", like passkeys (`sso.md`).
- **The sign-in page** (built 2026-11-21 on main): the code and "Sign in
  with a passkey" right on the page people land on (`LOGIN_URL`, allauth's
  code page, our template), no longer behind "Other sign-in options";
  single sign-on a little out of the way, behind "Sign in through your
  organization" (decided 2026-11-21).
- **An organization requiring a second factor** (decided 2026-11-21, a
  fourth level of its sign-in setting beside `sso.md`'s, or a switch
  next to "codes and passkeys" and "SSO allowed"; admins only, like the
  sign-in setting):
  - a passkey sign-in is enough (device plus PIN or fingerprint);
  - a code alone isn't: the authenticator app's code follows;
  - a sign-in through the organization's identity provider is enough
    (its own second factor is its business);
  - someone with neither a passkey nor an app who signs in by code is led
    to a page making them add one (a passkey or an app) before anything
    else; the same after a reset;
  - API tokens stay as they are (created after such a sign-in);
  - "SSO required" makes this moot (no codes at all).

## Done when

- `MFA_SUPPORTED_TYPES` with `webauthn` and `totp` (not
  `recovery_codes`), the two-factor step counting only TOTP (allauth's
  MFA adapter), its page without the passkey alternative's "security
  key" wording where it doesn't apply, the settings page's card, the
  reset through pages, API and CLI.
- Tests: a passkey owner signing in by code and Google without a second
  step; an app owner asked for the code after a code and after Google,
  not after a passkey; turning it on and off; resets by staff, admins,
  refused ones; the mail; SSO required deleting apps.
- `access.md`, `sso.md` and the help (`docs/sign-in.md`) say so.
