"""Changes of a person (in the Django admin: a client now, deactivated)
make their open editors check their access again"""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from biwak.collab import live


@receiver(post_save, sender=get_user_model())
def user_changed(sender, instance, update_fields=None, **kwargs):
    if update_fields and set(update_fields) <= {"last_login"}:
        return
    live.check_access(user=instance.pk)
