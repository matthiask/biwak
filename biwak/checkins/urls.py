from django.urls import path

from biwak.checkins import views


urlpatterns = [
    path(
        "projects/<int:pk>/checkins/", views.project_checkins, name="project_checkins"
    ),
    path("projects/<int:pk>/checkins/new/", views.question_new, name="question_new"),
    path("questions/<int:pk>/", views.question, name="question"),
    path("questions/<int:pk>/edit/", views.question_edit, name="question_edit"),
    path("questions/<int:pk>/pause/", views.question_pause, name="question_pause"),
    path("questions/<int:pk>/mail/", views.question_mail, name="question_mail"),
    path("questions/<int:pk>/answer/", views.question_answer, name="question_answer"),
    path(
        "questions/<int:pk>/people/<int:user_pk>/",
        views.question_person,
        name="question_person",
    ),
    path("answers/<int:pk>/comments/", views.answer_comment, name="answer_comment"),
]
