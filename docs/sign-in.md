# Signing in

Biwak has no passwords. You sign in with your email address:

- **A code by mail:** enter your address, Biwak mails you a code, type it
  in. It works when the mail is read on the phone and Biwak is open on the
  laptop.
- **A passkey:** your fingerprint, face or device PIN. After signing in by
  code, Biwak offers to add one; Settings, "Sign-in", adds and removes
  them.
- **Single sign-on:** "Sign in with Google" or "Sign in with Microsoft",
  where your organization has set it up.

## Single sign-on

Each organization decides how its people sign in (admins change it on the
organization's page, "Sign-in…"):

- **Codes and passkeys**, the default.
- **Single sign-on allowed:** the organization's Google Workspace or
  Microsoft Entra ID account in addition to codes and passkeys. Our own
  organization signs in like this with Google.
- **Single sign-on required:** only the organization's identity provider.
  Entering your address sends you there; codes are refused, passkeys
  aren't offered (switching to "required" removes them), and you sign in
  again through the provider every 24 hours, usually one click. API tokens
  expire 24 hours after you create them, and there are no calendar links.

A Google sign-in counts only for an account managed by the organization's
Google Workspace (its email domains), with your address in Biwak. A
Gmail address may always sign in with Google, unless the organization
requires Microsoft. A Microsoft sign-in counts only for the organization's
own tenant and addresses of its email domains. Deactivated people can't
sign in at all.

Settings, "Sign-in", shows the Google or Microsoft accounts connected to
yours ("Disconnect" ends the connection; the next sign-in through the
provider connects it again), your passkeys and your sessions.

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
change its email domains.
