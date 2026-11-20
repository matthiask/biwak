from django.urls import path

from biwak.projects import views


urlpatterns = [
    path("", views.project_list, name="projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project"),
    path("projects/<int:pk>/join/", views.project_join, name="project_join"),
    path("projects/<int:pk>/people/", views.project_people, name="project_people"),
    path(
        "projects/<int:pk>/people/<int:user_pk>/remove/",
        views.member_remove,
        name="member_remove",
    ),
]
