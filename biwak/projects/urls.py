from django.urls import path

from biwak.projects import all_projects, home, invitations, views


urlpatterns = [
    path("", home.dashboard, name="dashboard"),
    path("projects/", views.project_list, name="projects"),
    path("projects/all/", all_projects.all_projects_page, name="all_projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project"),
    path("projects/<int:pk>/join/", views.project_join, name="project_join"),
    path("projects/<int:pk>/people/", views.project_people, name="project_people"),
    path("projects/<int:pk>/people/add/", views.member_add, name="member_add"),
    path(
        "projects/<int:pk>/people/invite/",
        invitations.member_invite,
        name="member_invite",
    ),
    path("people/invite/", invitations.invite_people, name="invite_people"),
    path(
        "people/<int:pk>/invitation/resend/",
        invitations.invitation_resend,
        name="invitation_resend",
    ),
    path(
        "people/<int:pk>/invitation/withdraw/",
        invitations.invitation_withdraw,
        name="invitation_withdraw",
    ),
    path("projects/<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/archive/", views.project_archive, name="project_archive"),
    path("projects/<int:pk>/lists/new/", views.list_new, name="list_new"),
    path("projects/<int:pk>/lists/order/", views.list_order, name="list_order"),
    path("projects/<int:pk>/trash/", views.project_trash, name="project_trash"),
    path(
        "projects/<int:pk>/people/<int:user_pk>/notify/",
        views.member_notify,
        name="member_notify",
    ),
    path(
        "projects/<int:pk>/people/<int:user_pk>/remove/",
        views.member_remove,
        name="member_remove",
    ),
]
