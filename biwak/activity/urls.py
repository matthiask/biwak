from django.urls import path

from biwak.activity import views


urlpatterns = [
    path("feed/", views.feed, name="feed"),
    path("projects/<int:pk>/feed/", views.project_feed, name="project_feed"),
    path("items/<int:pk>/history/", views.item_history, name="item_history"),
    path(
        "projects/<int:pk>/notifications/",
        views.project_notifications,
        name="project_notifications",
    ),
    path(
        "items/<int:pk>/notifications/",
        views.item_notifications,
        name="item_notifications",
    ),
    path(
        "items/<int:pk>/subscribers/",
        views.item_subscribers,
        name="item_subscribers",
    ),
    path("items/<int:pk>/mentionable/", views.mentionable, name="mentionable"),
    path(
        "lists/<int:pk>/mentionable/",
        views.mentionable_list,
        name="mentionable_list",
    ),
    path(
        "projects/<int:pk>/mentionable/",
        views.mentionable_new,
        name="mentionable_new",
    ),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    path("lantern/", views.lantern, name="lantern"),
    path("lantern/menu/", views.lantern_menu, name="lantern_menu"),
    path("lantern/count/", views.lantern_count, name="lantern_count"),
    path("lantern/<int:pk>/", views.lantern_open, name="lantern_open"),
    path("lantern/read/", views.lantern_read, name="lantern_read"),
    path("lantern/unread/", views.lantern_unread, name="lantern_unread"),
    path("lantern/bookmark/", views.lantern_bookmark, name="lantern_bookmark"),
]
