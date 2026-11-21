from django.urls import path

from biwak.organizations import people, views


urlpatterns = [
    path("people/", people.people, name="people"),
    path("organizations/", views.organization_list, name="organizations"),
    path("organizations/new/", views.organization_create, name="organization_create"),
    path("organizations/<int:pk>/", views.organization_detail, name="organization"),
    path(
        "organizations/<int:pk>/edit/",
        views.organization_edit,
        name="organization_edit",
    ),
    path(
        "organizations/<int:pk>/merge/",
        views.organization_merge,
        name="organization_merge",
    ),
    path(
        "organizations/<int:pk>/delete/",
        views.organization_delete,
        name="organization_delete",
    ),
    path(
        "people/<int:pk>/organization/",
        views.person_organization,
        name="person_organization",
    ),
]
