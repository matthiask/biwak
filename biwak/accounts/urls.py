from django.urls import path
from django.views.generic import RedirectView

from biwak.accounts import signin, views


urlpatterns = [
    path(
        "people/<int:pk>/image/<str:version>.webp",
        views.person_image,
        name="person_image",
    ),
    path(
        "people/<int:pk>/image/remove/",
        views.person_image_remove,
        name="person_image_remove",
    ),
    path("settings/image/", views.settings_image, name="settings_image"),
    path("settings/", views.settings, name="settings"),
    path(
        "settings/notifications/",
        views.settings_notifications,
        name="settings_notifications",
    ),
    path("settings/name/", views.settings_name, name="settings_name"),
    path("settings/keyboard/", views.settings_keyboard, name="settings_keyboard"),
    path("settings/appearance/", views.settings_appearance, name="settings_appearance"),
    # The notification settings were here before the settings page
    path(
        "notifications/",
        RedirectView.as_view(pattern_name="settings", permanent=True),
    ),
    path("sessions/<int:pk>/end/", signin.end_session, name="session_end"),
    path(
        "connected/<int:pk>/disconnect/",
        signin.disconnect,
        name="social_disconnect",
    ),
    path("api-tokens/", views.api_tokens, name="api_tokens"),
    path(
        "api-tokens/<int:pk>/delete/",
        views.api_token_delete,
        name="api_token_delete",
    ),
    path("calendar/", views.calendar_link, name="calendar_link"),
    path("passkey-offer/", views.passkey_offer, name="passkey_offer"),
    path("two-factor/", signin.two_factor_setup, name="two_factor_setup"),
    path("cli-login/", views.cli_login, name="cli_login"),
]
