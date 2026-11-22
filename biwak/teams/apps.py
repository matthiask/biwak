from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TeamsConfig(AppConfig):
    name = "biwak.teams"
    verbose_name = _("teams")
