from django.urls import path

from biwak.files import board, views


urlpatterns = [
    path(
        "projects/<int:pk>/attachments/",
        views.attachment_upload,
        name="attachment_upload",
    ),
    path("attachments/<str:key>/<path:name>", views.attachment, name="attachment"),
    # The message board
    path(
        "projects/<int:pk>/messages/", board.project_messages, name="project_messages"
    ),
    path("projects/<int:pk>/messages/new/", board.message_new, name="message_new"),
    path("messages/<int:pk>/", board.message, name="message"),
    path("messages/<int:pk>/edit/", board.message_edit, name="message_edit"),
    path("messages/<int:pk>/pin/", board.message_pin, name="message_pin"),
]
