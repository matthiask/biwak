from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CheckinsConfig(AppConfig):
    name = "biwak.checkins"
    verbose_name = _("check-ins")
