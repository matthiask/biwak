"""Signing out ends pushes on that browser (specs/web-push.md)"""

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver


@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    from biwak.accounts.views import signed_out

    if request is not None:
        signed_out(request, user)
