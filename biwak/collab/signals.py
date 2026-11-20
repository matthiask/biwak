"""Changes outside the operations (the Django admin) make the open editors
check their access again: a person made a client or deactivated, a project
made limited or archived"""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
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
