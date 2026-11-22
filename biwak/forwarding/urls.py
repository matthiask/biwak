from django.urls import path

from biwak.forwarding import views


urlpatterns = [
    path("forwarded/", views.forwarded, name="forwarded"),
    path(
        "forwarded/<int:pk>/message/",
        views.file_message,
        name="forwarded_file_message",
    ),
    path("forwarded/<int:pk>/todo/", views.file_todo, name="forwarded_file_todo"),
    path("forwarded/<int:pk>/delete/", views.delete, name="forwarded_delete"),
    path(
        "forwarded/<int:pk>/files/<str:key>/<path:name>",
        views.download,
        name="forwarded_download",
    ),
]
