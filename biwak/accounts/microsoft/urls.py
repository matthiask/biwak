from allauth.socialaccount.providers.oauth2.urls import default_urlpatterns

from biwak.accounts.microsoft.provider import EntraProvider


urlpatterns = default_urlpatterns(EntraProvider)
