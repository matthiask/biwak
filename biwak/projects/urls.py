from django.urls import path

from biwak.projects import views


urlpatterns = [
    path("", views.project_list, name="projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project"),
    path("projects/<int:pk>/join/", views.project_join, name="project_join"),
]
