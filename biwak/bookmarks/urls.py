from django.urls import path

from biwak.bookmarks import views


urlpatterns = [
    path("bookmarks/", views.bookmarks, name="bookmarks"),
    path("items/<int:pk>/bookmark/", views.item_bookmark, name="item_bookmark"),
    path(
        "projects/<int:pk>/bookmark/", views.project_bookmark, name="project_bookmark"
    ),
    path(
        "projects/<int:pk>/links/",
        views.project_link_create,
        name="project_link_create",
    ),
    path(
        "projects/<int:pk>/links/order/",
        views.project_link_order,
        name="project_link_order",
    ),
    path("items/<int:pk>/links/", views.item_link_create, name="item_link_create"),
    path("items/<int:pk>/links/order/", views.item_link_order, name="item_link_order"),
    path("links/<int:pk>/edit/", views.link_edit, name="link_edit"),
    path("links/<int:pk>/delete/", views.link_delete, name="link_delete"),
]
