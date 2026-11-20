from django.urls import path

from biwak.activity import views


urlpatterns = [
    path("feed/", views.feed, name="feed"),
    path("projects/<int:pk>/feed/", views.project_feed, name="project_feed"),
    path("items/<int:pk>/history/", views.item_history, name="item_history"),
    path("people/<int:pk>/feed/", views.person_feed, name="person_feed"),
]
