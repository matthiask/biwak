from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PaletteConfig(AppConfig):
    name = "biwak.palette"
    verbose_name = _("command palette")
