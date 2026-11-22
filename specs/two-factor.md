# Passkeys as a way in, authenticator apps as an optional second factor

**Status:** built (2026-11-21). Sign-in in general (codes, passkeys,
the sign-in page, sessions) is in `access.md`; single sign-on in
`sso.md`.

Trap: allauth counts passkeys as a second factor by default, so once
somebody had one, signing in by code or Google led to a page asking for
an authenticator code nobody had set up. `MFAAdapter.is_mfa_enabled()`
below is what prevents that.

## Rules (decided 2026-11-21)

- **Passkeys are a way in, not a second factor:** a code, the
  organization's identity provider and a passkey are each enough alone.
  allauth's two-factor step never asks for a passkey.
- **Every key added is a passkey** (decided 2026-11-21): a
  discoverable credential that verifies the person (PIN, fingerprint),
  never a key that only proves it's present; no "Passwordless" checkbox.
- **Authenticator apps (TOTP) are an optional second factor:** anybody
  may turn one on in their settings (a QR code and a code to confirm, one
  app per person); then signing in by code or through the identity
  provider asks for the app's code. A passkey sign-in stays enough alone
  (device plus PIN or fingerprint). Turning the app off needs its code
  once more.
- **Confirming who one is** (allauth's reauthentication before sensitive
  changes) takes the app or a passkey for people with an app, never a
  code by mail: a code by mail could otherwise add a passkey, which signs
  in alone, or turn the app off (decided 2026-11-21, the most secure
  reading). Confirming with a passkey needs the PIN or fingerprint, as
  signing in does (decided 2026-11-22, `MFA_WEBAUTHN_USER_VERIFICATION =
  "required"`; allauth's default "preferred" let a key only proving it's
  present do). Every key was already registered with user verification
  (allauth requires it for passkeys, and every key added is one), which
  is why requiring it for confirming breaks no key people have.
- **A mail on every change** (decided 2026-11-21): adding
  or removing a passkey and turning the app on or off mail the person
  what changed and when, with "if it wasn't you, tell an admin", so a
  change somebody else made with their session is noticed.
- **No recovery codes:** losing the app means signing in with a passkey,
  or asking for a reset.
- **Resetting someone's sign-in** (decided 2026-11-21: one recovery and
  incident action, the consistent and secure one, for "lost my phone or
  laptop" and "someone else may have had access"): "Reset sign-in…" with the
  split of `activation.md`: staff reset clients, admins also own staff
  and externals; nobody resets themselves this way (they change their
  own in the settings). Offered whenever the person has any of an
  authenticator app, passkeys or API tokens; it deletes all of them,
  ends their sessions and mails them what was removed and by whom ("Ada
  reset your sign-in to Biwak", a line per kind: "your authenticator
  app", "2 passkeys", "1 API token"), so a reset they didn't ask for is
  noticed. They sign in by code or through their organization's identity
  provider then and set up again; where a second factor is required,
  they're led to the setup page first. With none of them nothing
  happens (no mail, sessions stay). The audit log has it. The question
  and the message afterwards speak about the person ("their
  authenticator app") and mention the mail only when one goes out (not
  to inactive people or bounced addresses).
- **Organizations requiring single sign-on:** no passkeys and no
  authenticator apps (the identity provider does that); existing ones are
  deleted when the organization switches to "required" (`sso.md`).
- **Organizations requiring a second factor** (a switch beside the
  sign-in levels of `sso.md`, since it combines with "codes" and "SSO
  allowed"; admins only, like the sign-in setting):
  - a passkey sign-in is enough;
  - a code alone isn't: the authenticator app's code follows;
  - a sign-in through the organization's identity provider is enough
    (its own second factor is its business); a person's own app is still
    asked for there, as everywhere, the requirement only doesn't need it.
    Only its own Workspace (`hd` one of its domains) or Entra tenant
    (`tid`, an address of its domains) counts, checked against the
    organization as it is now: a personal Gmail account signing in with
    Google where single sign-on is allowed is like a code (decided
    2026-11-21);
  - someone with neither a passkey nor an app who signs in by code is led
    to a page making them add one (a passkey or an app) before anything
    else; the same after a reset;
  - someone with a passkey but no app who signs in by code is refused
    ("sign in with your passkey"): letting them add an app after a code
    alone would make the code enough (decided 2026-11-21);
  - API tokens stay as they are (created after such a sign-in);
  - "SSO required" makes it moot (no codes at all).

## Where each rule is enforced

- **The two-factor step** counts only authenticator apps:
  `adapters.MFAAdapter.is_mfa_enabled()` (`MFA_ADAPTER`), which allauth's
  `AuthenticateStage` and its page ask; passkeys count only when asked
  about alone (allauth's reauthentication offering them); people whose
  organization requires single sign-on have no second factor there. The
  page is `signin.TwoFactorView` (`/accounts/2fa/authenticate/`,
  `mfa/authenticate.html`): the code field only; a post without a code is
  a missing code, never a passkey.
- **The settings' card** ("Authenticator app", `accounts/settings.html`):
  `signin.activate_app` (`/accounts/2fa/totp/activate/`, a modal: QR code,
  key, the code; allauth's reauthentication first; refused where single
  sign-on is required) and `signin.deactivate_app` (`…/deactivate/`: the
  app's code through allauth's `ReauthenticateForm`, then its
  `deactivate_totp` flow). `MFA_SUPPORTED_TYPES = ["webauthn", "totp"]`,
  no recovery codes, `MFA_TOTP_ISSUER = "Biwak"`.
- **Confirming who one is:** `AccountAdapter.get_reauthentication_methods()`
  leaves out the code by mail for people with an app;
  `signin.reauthenticate(…, by_code=True)` sends the code pages to the
  app's.
- **Adding a passkey:** `signin.AddPasskeyView` (allauth's, at
  `/accounts/2fa/webauthn/add/` through `signin.add_passkey`) registers
  with `begin_registration(user, True)`: resident key and user
  verification required, which the server checks again on the answer
  (fido2's state, `AddPasskeyForm.clean()`); its template
  (`mfa/webauthn/add_form.html`) gives allauth's script a hidden, ticked
  "passwordless" box. Whether the key really is discoverable only the
  browser knows; one that isn't can't sign in.
- **Mails on changes:** allauth's notification hook
  (`AccountAdapter.send_notification_mail`, which its passkey and TOTP
  flows call) sends `security_mails.send()` for `webauthn_added`,
  `webauthn_removed`, `totp_activated`, `totp_deactivated` through the
  outbox (`accounts/security_change.txt`, `Kind.ACCOUNT`; not to
  inactive people or bounced addresses). allauth's other notifications
  stay off (`ACCOUNT_EMAIL_NOTIFICATIONS` unset).
- **Resets:** `activation.can_reset_sign_in()` (`can_change()`, not
  oneself), `activation.sign_in()` (what the person has: `SignIn(app,
  passkeys, api_tokens)`) and `activation.reset_sign_in()` in
  `biwak/organizations/activation.py`: deletes the app, the passkeys and
  the API tokens, ends the sessions
  (`UserSession.end()`, `live.check_access()`), mails through the outbox
  (`accounts/sign_in_reset.txt`, `Kind.ACCOUNT`, from the actor, not
  to inactive people or bounced addresses). The page
  `/people/<id>/reset-sign-in/` (offered on the person's page and in the
  palette only when there's something to remove), `POST
  /api/v1/people/{id}/reset-sign-in/` (`reset`: whether there was
  anything, `removed`: `{app, passkeys, api_tokens}`; the old
  `…/reset-two-factor/` stays as an alias), `biwak people reset-sign-in
  ID` (`reset-two-factor` stays as a hidden alias). Migration `accounts.0017`
  audits `mfa_authenticator` without `data` (the app's secret, the
  passkey's key) and `last_used_at`.
- **SSO required:** `sso.enforce_required()` deletes every authenticator;
  `signin.activate_app` refuses, the card isn't shown,
  `passkeys.passkey_added` deletes one coming through anyway.
- **Requiring a second factor:** `Organization.requires_two_factor`
  ("Require a second factor" in the sign-in modal, next to the levels;
  `two_factor_required` is false where single sign-on is required).
  `two_factor.refuse_login()` from `AccountAdapter.pre_login` (fails
  closed: no record counts as a code); `two_factor.setup_required()`,
  checked on every request by `two_factor.setup_middleware` (pages
  redirect to `/accounts/two-factor/`, htmx gets `HX-Redirect`, the API
  with the session 403) and for websockets by `sso.session_alive()`; the
  paths setting one up needs stay open (`SETUP_PATHS`). A sign-in through
  the organization's identity provider is recognized by the session's
  record (`sso.remember_sign_in()`: person, organization, address,
  provider, `hd`, `tid`), without the 24 hours of SSO required, and
  `sso.is_organization_idp()` decides on the claims (also in
  `refuse_login()`, from the social login allauth passes to `pre_login`).

## Not done (known, open)

- The app's secret is stored as allauth stores it, unencrypted
  (`MFAAdapter.encrypt()` could add it).
- Sessions signed in by code before an organization starts requiring a
  second factor stay for people who have one.
- Merging or moving people between organizations doesn't look at the
  switch, only at the sign-in levels of `sso.md`.
