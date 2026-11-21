from django.urls import path

from biwak.reactions import views


urlpatterns = [
    path("items/<int:pk>/reactions/", views.item_reactions, name="item_reactions"),
    path(
        "items/<int:pk>/reactions/remove/",
        views.item_reaction_remove,
        name="item_reaction_remove",
    ),
    path(
        "comments/<int:pk>/reactions/remove/",
        views.comment_reaction_remove,
        name="comment_reaction_remove",
    ),
    path(
        "comments/<int:pk>/reactions/",
        views.comment_reactions,
        name="comment_reactions",
    ),
]
