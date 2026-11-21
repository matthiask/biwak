"""allauth's Microsoft provider with the tenant (specs/sso.md): a sign-in
counts only for the organization's own tenant, the ``tid`` claim of the ID
token, which Graph's ``/me`` doesn't give. Set as the provider's
``provider_class`` in ``SOCIALACCOUNT_PROVIDERS``."""

from allauth.socialaccount.providers.microsoft.provider import (
    MicrosoftGraphProvider,
)

from biwak.accounts.microsoft.views import EntraOAuth2Adapter


class EntraProvider(MicrosoftGraphProvider):
    oauth2_adapter_class = EntraOAuth2Adapter
    # This package's views and URLs (allauth derives them from it)
    package = "biwak.accounts.microsoft"

    def get_default_scope(self):
        # The ID token (``openid``) carries the tenant
        return ["openid", "email", "profile", "User.Read"]

    def extract_email_addresses(self, data):
        # Entra ID doesn't verify addresses: never matched as verified by
        # allauth itself; biwak.accounts.sso decides with the tenant
        return []


provider_classes = [EntraProvider]
