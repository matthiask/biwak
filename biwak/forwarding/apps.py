from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ForwardingConfig(AppConfig):
    name = "biwak.forwarding"
    verbose_name = _("forwarded mails")
