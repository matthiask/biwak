from django.urls import path

from biwak.organizations import people, views


urlpatterns = [
    path("people/", people.people, name="people"),
    path("people/<int:pk>/", people.person, name="person"),
    path("people/<int:pk>/activate/", people.person_activate, name="person_activate"),
    path("people/<int:pk>/name/", people.person_name, name="person_name"),
    path("people/<int:pk>/away/", people.person_away, name="person_away"),
    path("people/<int:pk>/back/", people.person_back, name="person_back"),
    path(
        "people/<int:pk>/deactivate/",
        people.person_deactivate,
        name="person_deactivate",
    ),
    path(
        "people/<int:pk>/reset-sign-in/",
        people.person_reset_sign_in,
        name="person_reset_sign_in",
    ),
    path("organizations/", views.organization_list, name="organizations"),
    path("organizations/new/", views.organization_create, name="organization_create"),
    path("organizations/<int:pk>/", views.organization_detail, name="organization"),
    path(
        "organizations/<int:pk>/edit/",
        views.organization_edit,
        name="organization_edit",
    ),
    path(
        "organizations/<int:pk>/sign-in/",
        views.organization_signin,
        name="organization_signin",
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
