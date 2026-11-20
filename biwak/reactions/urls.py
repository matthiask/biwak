from django.urls import path

from biwak.reactions import views


urlpatterns = [
    path("items/<int:pk>/reactions/", views.item_reactions, name="item_reactions"),
    path(
        "comments/<int:pk>/reactions/",
        views.comment_reactions,
        name="comment_reactions",
    ),
]
