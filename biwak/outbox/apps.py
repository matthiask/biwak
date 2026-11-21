from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OutboxConfig(AppConfig):
    name = "biwak.outbox"
    verbose_name = _("outgoing mail")
