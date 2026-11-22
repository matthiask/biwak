from django.urls import path

from biwak.teams import views


urlpatterns = [
    path("teams/new/", views.team_create, name="team_create"),
    path("teams/<int:pk>/", views.team_detail, name="team"),
    path("teams/<int:pk>/edit/", views.team_edit, name="team_edit"),
    path("teams/<int:pk>/delete/", views.team_delete, name="team_delete"),
]
