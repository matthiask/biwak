from django.urls import path

from biwak.accounts import views


urlpatterns = [
    path("api-tokens/", views.api_tokens, name="api_tokens"),
    path(
        "api-tokens/<int:pk>/delete/",
        views.api_token_delete,
        name="api_token_delete",
    ),
    path("calendar/", views.calendar_link, name="calendar_link"),
    path("cli-login/", views.cli_login, name="cli_login"),
]
