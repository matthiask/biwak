from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LiveConfig(AppConfig):
    name = "biwak.live"
    verbose_name = _("live updates")
