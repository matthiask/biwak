from django.urls import path

from biwak.collab.consumers import DocConsumer


websocket_urlpatterns = [path("ws/docs/<int:pk>", DocConsumer.as_asgi())]
