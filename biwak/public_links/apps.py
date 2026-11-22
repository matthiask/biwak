from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PublicLinksConfig(AppConfig):
    name = "biwak.public_links"
    verbose_name = _("public links")
