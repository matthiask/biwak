"""The ID token's tenant (``tid``) next to Graph's profile (specs/sso.md)"""

import time

from allauth.core.internal.deferred import jwt
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.providers.microsoft.views import (
    MicrosoftGraphOAuth2Adapter,
)
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2CallbackView,
    OAuth2LoginView,
)


ISSUER = "https://login.microsoftonline.com/{tid}/v2.0"


def tenant_claims(id_token, *, client_id):
    """The ID token's claims, checked: for this app (``aud``), not expired,
    issued by its own tenant (``iss`` names ``tid``). The token comes
    straight from Microsoft's token endpoint over TLS (the code exchange),
    which lets OpenID Connect skip its signature (Core 1.0, 3.1.3.7), as
    allauth does for Google."""
    if not id_token:
        raise OAuth2Error("No ID token: the scope needs openid")
    try:
        claims = jwt.decode(
            id_token,
            options={
                "verify_signature": False,
                "verify_aud": True,
                "verify_exp": True,
                "require": ["aud", "exp", "iss", "tid", "oid"],
            },
            audience=client_id,
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise OAuth2Error("Invalid ID token") from exc
    tid = claims.get("tid")
    if not isinstance(tid, str) or claims.get("iss") != ISSUER.format(tid=tid):
        raise OAuth2Error("The ID token's issuer isn't its tenant")
    if claims.get("iat", time.time()) > time.time() + 60:
        raise OAuth2Error("The ID token is from the future")
    return claims


class EntraOAuth2Adapter(MicrosoftGraphOAuth2Adapter):
    def complete_login(self, request, app, token, **kwargs):
        if not self.did_fetch_access_token:
            # Only tokens Biwak fetched itself: not handed to it
            raise OAuth2Error("Tokens must come from the code exchange")
        claims = tenant_claims(
            kwargs.get("response", {}).get("id_token"), client_id=app.client_id
        )
        headers = {"Authorization": f"Bearer {token.token}"}
        with get_adapter().get_requests_session() as sess:
            response = sess.get(
                self.profile_url, params=self.profile_url_params, headers=headers
            )
            try:
                data = response.json()
            except ValueError as exc:
                raise OAuth2Error("Invalid JSON from Microsoft Graph") from exc
        if not isinstance(data, dict) or "id" not in data:
            raise OAuth2Error("Error retrieving the Microsoft profile")
        if str(data.get("id")) != claims["oid"]:
            raise OAuth2Error("Graph's profile isn't the ID token's user")
        data["tid"] = claims["tid"]
        return self.get_provider().sociallogin_from_response(request, data)


oauth2_login = OAuth2LoginView.adapter_view(EntraOAuth2Adapter)
oauth2_callback = OAuth2CallbackView.adapter_view(EntraOAuth2Adapter)
