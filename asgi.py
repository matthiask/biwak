import os
from pathlib import Path

from speckenv import read_speckenv


read_speckenv(Path(__file__).parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "biwak.settings")

from django.core.asgi import get_asgi_application  # noqa: E402


django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from biwak.collab.routing import websocket_urlpatterns  # noqa: E402


application = ProtocolTypeRouter({
    "http": django_application,
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
