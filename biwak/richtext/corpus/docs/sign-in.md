# Signing in

Biwak has no passwords. You sign in with your email address:

- **A code by mail:** enter your address, Biwak mails you a code, type it
  in. It works when the mail is read on the phone and Biwak is open on the
  laptop.
- **A passkey:** your fingerprint, face or device PIN. After signing in by
  code, Biwak offers to add one; Settings, "Sign-in", adds and removes
  them.
- **Single sign-on:** "Sign in through your organization" on the
  sign-in page, then "Sign in with Google" or "Sign in with Microsoft",
  where your organization has set it up. Where it requires single
  sign-on, entering your address sends you there.

## An authenticator app

A second step, if you want one: Settings, "Sign-in", "Authenticator app",
"Set up…" shows a QR code for an app on your phone (any authenticator
app); enter the code it shows to turn it on. From then on, signing in by
code or through Google or Microsoft asks for the app's code too. A passkey
is enough alone: it already needs your device and its PIN or fingerprint.

- **Confirming it's you** (adding a passkey, setting things up) asks for
  the app's code or a passkey then, not for a code by mail.
- **Turning it off** ("Turn off…") needs a code from the app.
- **Lost the app?** A passkey still signs you in, but turning the app off
  needs its code: without the app, ask for a reset (below). There are no
  recovery codes.

**Lost your phone or laptop, or someone else may have had access?** Ask
for a reset: on your page, "Reset sign-in…" removes your authenticator
app, your passkeys and your API tokens, signs you out everywhere and
mails you what was removed and by whom. You sign in with a code or
through your organization's sign-in then and set things up again; where
your organization requires a second factor, Biwak leads you to adding
one first. Staff reset clients, admins reset everybody else; nobody
resets themselves. The CLI: `biwak people reset-sign-in ID`.

Adding or removing a passkey and turning the app on or off sends you a
mail saying what changed and when: if it wasn't you, tell an admin.

People whose organization requires single sign-on have no authenticator
app: their identity provider asks for a second step if it wants one.

## Organizations requiring a second factor

Admins can require a second factor for an organization (its page,
"Sign-in…", "Require a second factor"). Then a code by mail alone isn't
enough for its people:

- a passkey is enough, and so is a sign-in through the organization's
  identity provider (its own Google Workspace or Microsoft tenant, not a
  personal Gmail account);
- after a code, the authenticator app's code follows;
- people with a passkey but no app sign in with the passkey (a code alone
  is refused);
- people with neither add a passkey or set up an app right after signing
  in by code, before anything else; the same after a reset, or when the
  setting is switched on.

API tokens made before keep working. Where single sign-on is required,
the setting doesn't matter: there are no codes.

## Single sign-on

Each organization decides how its people sign in (admins change it on the
organization's page, "Sign-in…"):

- **Codes and passkeys**, the default.
- **Single sign-on allowed:** the organization's Google Workspace or
  Microsoft Entra ID account in addition to codes and passkeys. Our own
  organization signs in like this with Google.
- **Single sign-on required:** only the organization's identity provider.
  Entering your address sends you there; codes are refused, passkeys
  and authenticator apps aren't offered (switching to "required" removes
  them), and you sign in
  again through the provider every 24 hours, usually one click. API tokens
  expire 24 hours after you create them, and there are no calendar links.

A Google sign-in counts only for an account managed by the organization's
Google Workspace (its email domains), with your address in Biwak. A
Gmail address may sign in with Google where the organization allows
single sign-on or doesn't use it, not where it requires it. A Microsoft sign-in counts only for the organization's
own tenant and addresses of its email domains. Deactivated people can't
sign in at all.

Settings, "Sign-in", shows the Google or Microsoft accounts connected to
yours ("Disconnect" ends the connection; the next sign-in through the
provider connects it again), your passkeys, your authenticator app and
your sessions.

## Setting up single sign-on (admins)

The installation needs an app registration per provider; its client ID
and secret are settings of the server (`GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`,
`MICROSOFT_CLIENT_SECRET`). Without them, the provider can't be chosen.

**Google:** in the Google Cloud console, "APIs & Services", create an
OAuth client ID of type "Web application" with the authorized redirect
URI `https://YOUR-BIWAK/accounts/google/login/callback/`. The OAuth
consent screen asks for the scopes `openid`, `email` and `profile`; make
it "External" if people of other Workspaces sign in too.

**Microsoft:** in the Microsoft Entra admin center, "App registrations",
register an app for "Accounts in any organizational directory
(multitenant)" with the web redirect URI
`https://YOUR-BIWAK/accounts/microsoft/login/callback/`, and create a
client secret under "Certificates & secrets". It asks for `openid`,
`email`, `profile` and `User.Read`; an organization's administrator may
have to consent once for their tenant.

Then, on the organization's page:

1. Check the organization's email domains: Google's sign-ins count for
   its Workspace domains, Microsoft's for addresses of these domains.
   Microsoft: copy the "Directory (tenant) ID" from the organization's
   Entra admin center.
2. "Sign-in…": choose the provider and "allowed" first, and try it.
3. Switch to "required" when everybody can sign in through the provider.
   If you belong to the organization yourself, sign in through the
   provider first.

While an organization signs in through single sign-on, only admins
change its email domains. Only admins move people out of an organization
requiring it. Staff merge organizations signing in the same way; merging
into one signing in more strictly is for admins, who confirm what
happens to the people moving; merging into one signing in less strictly
isn't possible: change its sign-in first.
