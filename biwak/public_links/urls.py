from django.urls import path

from biwak.public_links import views


urlpatterns = [
    path("items/<int:pk>/share/", views.item_share, name="item_share"),
    path("public-links/", views.public_links, name="public_links"),
    path(
        "public-links/<int:pk>/stop/", views.public_link_stop, name="public_link_stop"
    ),
    path("p/<str:token>/", views.public_page, name="public_page"),
    path("p/<str:token>/download/", views.public_download, name="public_download"),
    path("p/<str:token>/preview/", views.public_preview, name="public_preview"),
    path(
        "p/<str:token>/attachments/<str:key>/<path:name>",
        views.public_attachment,
        name="public_attachment",
    ),
]
