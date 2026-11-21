"""Authenticator apps (TOTP) as an optional second factor, passkeys as a way
in (specs/two-factor.md). Where each rule is enforced:

- the two-factor step after a sign-in by code or through Google or
  Microsoft asks for the app's code (``adapters.MFAAdapter.is_mfa_enabled``,
  allauth's ``AuthenticateStage``); a passkey sign-in is enough alone;
- confirming who one is (allauth's reauthentication) isn't a code by mail
  for people with an app (``adapters.AccountAdapter
  .get_reauthentication_methods``, ``signin.reauthenticate``): the app or a
  passkey, or a code by mail would be enough to turn the app off or add a
  passkey.
"""

from allauth.mfa.models import Authenticator


def has_app(user):
    """Whether the person has an authenticator app"""
    return (
        user.is_authenticated
        and Authenticator.objects.filter(
            user=user, type=Authenticator.Type.TOTP
        ).exists()
    )


def code_confirms(user):
    """Whether a code by mail confirms who the person is (allauth's
    reauthentication): not for people with an app"""
    return not has_app(user)
