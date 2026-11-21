# Passkeys as a way in, authenticator apps as an optional second factor

The trigger (2026-11-21, after deploying): once somebody had a passkey,
signing in by code or Google led to allauth's two-factor step, whose page
asks for an "authenticator code" nobody set up (passkeys counted as a
second factor).

**Status:** spec (2026-11-21), decided the same day. Not built.

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
