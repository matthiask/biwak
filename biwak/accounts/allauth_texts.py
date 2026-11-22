"""allauth's texts that people see when signing in, here so that our catalog
has them (specs/languages.md, decided 2026-11-22): its German says "Sie" and
its own words; ours wins (``LOCALE_PATHS`` comes before the apps' catalogs).
Exactly allauth's English, nothing imports this module. The Django admin
keeps Django's German."""

from django.utils.translation import gettext_noop as _, pgettext_noop


TEXTS = [
    # Errors and labels of the sign-in forms (account/adapter.py, fields.py)
    _("This account is currently inactive."),
    _("Incorrect code."),
    _("Invalid login."),
    _("Too many failed login attempts. Try again later."),
    _("Be patient, you are sending too many requests."),
    _("Send me a sign-in code"),
    _("Use authenticator app or code"),
    _("Use a security key"),
    _("Email"),
    _("Code"),
    pgettext_noop("field label", "Login"),
    # Two factors (mfa/)
    _("Authenticator code"),
    _("Master key"),
    _("Backup key"),
    _("Key nr. {number}"),
    # Google and Microsoft (socialaccount/adapter.py)
    _(
        "An account already exists with this email address. Please sign in to"
        " that account first, then connect your %s account."
    ),
    _("Invalid token."),
    _("The third-party account is already connected to a different account."),
    _("You cannot disconnect your last remaining third-party account."),
    # The mails (templates/account/email/)
    _("Hello from %(site_name)s!"),
    _("Thank you for using %(site_name)s!\n%(site_domain)s"),
    _(
        "Your sign-in code is listed below. Please enter it in your open browser"
        " window."
    ),
    _("This mail can be safely ignored if you did not initiate this action."),
    _("Sign-In Code"),
    _(
        "You are receiving this email because you, or someone else, tried to"
        " access an account with email %(email)s. However, we do not have any"
        " record of such an account in our database."
    ),
    _("If it was you, you can sign up for an account using the link below."),
    _("Unknown Account"),
    # Messages after signing in and out, passkeys, apps, connections,
    # sessions (templates/*/messages/)
    _("Successfully signed in as %(name)s."),
    _("You have signed out."),
    _("A sign-in code has been sent to %(recipient)s."),
    _("Authenticator app activated."),
    _("Authenticator app deactivated."),
    _("Security key added."),
    _("Security key removed."),
    _("The third-party account has been connected."),
    _("The third-party account has been disconnected."),
    _("Signed out of all other sessions."),
]
