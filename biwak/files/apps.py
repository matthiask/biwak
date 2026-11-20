from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class FilesConfig(AppConfig):
    name = "biwak.files"
    verbose_name = _("files")

    def ready(self):
        from biwak.files import models  # noqa: F401, the signal
