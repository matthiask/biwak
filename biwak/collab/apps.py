from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CollabConfig(AppConfig):
    name = "biwak.collab"
    verbose_name = _("live editing")

    def ready(self):
        from biwak.collab import signals  # noqa: F401
