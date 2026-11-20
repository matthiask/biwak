from django.urls import path

from biwak.files import views


urlpatterns = [
    path(
        "projects/<int:pk>/attachments/",
        views.attachment_upload,
        name="attachment_upload",
    ),
    path("attachments/<str:key>/<path:name>", views.attachment, name="attachment"),
]
