from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = "biwak.accounts"
    verbose_name = _("accounts")

    def ready(self):
        from biwak.accounts import passkeys, signals  # noqa: F401
