from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class InboundConfig(AppConfig):
    name = "biwak.inbound"
    verbose_name = _("replies by mail")
