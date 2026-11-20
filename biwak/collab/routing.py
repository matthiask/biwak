"""The websockets (asgi.py); frontend/collab.js connects to /ws/docs/<id>"""

from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.urls import path

from biwak.collab.consumers import DocConsumer


websocket_urlpatterns = [path("ws/docs/<int:pk>", DocConsumer.as_asgi())]


class AllowedHostsOriginValidator(OriginValidator):
    """Channels' validator of the same name, reading ``ALLOWED_HOSTS`` when
    a websocket connects instead of once: the session cookie authenticates,
    so only pages of our hosts may connect"""

    def __init__(self, application):
        super().__init__(application, [])

    def valid_origin(self, parsed_origin):
        self.allowed_origins = settings.ALLOWED_HOSTS or (
            ["localhost", "127.0.0.1", "[::1]"] if settings.DEBUG else []
        )
        return super().valid_origin(parsed_origin)


def websockets():
    return AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    )
