"""Changes outside the operations make the open editors and pages
(``/ws/live/``) check their access again: a person made a client or
deactivated, a project made limited or archived (the Django admin), and
logging out, here or everywhere"""

from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from biwak.collab import live
from biwak.projects.models import Project


@receiver(post_save, sender=get_user_model())
def user_changed(sender, instance, update_fields=None, **kwargs):
    if update_fields and set(update_fields) <= {"last_login"}:
        return
    live.check_access(user=instance.pk)


@receiver(post_save, sender=Project)
def project_changed(sender, instance, **kwargs):
    if not kwargs.get("created"):
        live.check_access(project=instance.pk)


@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    """Sent before the session is deleted: the session's websockets close
    by its key, whenever the message reaches them"""
    if user is not None:
        live.check_access(user=user.pk, session=request.session.session_key)


@receiver(post_delete, sender=UserSession)
def session_ended(sender, instance, **kwargs):
    """Logging out everywhere (usersessions ends the others), or a session
    gone anyway"""
    live.check_access(user=instance.user_id, session=instance.session_key)
