from django.urls import path

from biwak.items import across, assigning, by_due, from_text_views, views


urlpatterns = [
    path("todos/", by_due.todos_by_due, name="todos"),
    path("todos/assign/", assigning.todos_assign, name="todos_assign"),
    path("todos/move/", assigning.todos_move, name="todos_move_selected"),
    path("todos/dates/", assigning.todos_dates, name="todos_dates"),
    path("projects/<int:pk>/todos/", by_due.project_todos, name="project_todos"),
    path("calendar/<str:token>.ics", by_due.calendar_feed, name="calendar_feed"),
    path("lists/<int:pk>/", views.todolist, name="list"),
    path("lists/<int:pk>/completed/", views.completed_todos, name="list_completed"),
    path("lists/<int:pk>/groups/", views.group_create, name="group_create"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("groups/<int:pk>/move/", views.group_move, name="group_move"),
    path("groups/<int:pk>/rename/", views.group_rename, name="group_rename"),
    path("lists/<int:pk>/edit/", views.list_edit, name="list_edit"),
    path("lists/<int:pk>/todos/move/", views.todos_move, name="todos_move"),
    path("lists/<int:pk>/archive/", views.item_archive, name="list_archive"),
    path("lists/<int:pk>/copy/", across.list_copy, name="list_copy"),
    path(
        "lists/<int:pk>/from-text/",
        from_text_views.list_from_text,
        name="list_from_text",
    ),
    path(
        "lists/<int:pk>/from-text/preview/",
        from_text_views.list_from_text_preview,
        name="list_from_text_preview",
    ),
    path("todos/<int:pk>/", views.todo, name="todo"),
    path("todos/<int:pk>/edit/", views.todo, {"edit": True}, name="todo_edit"),
    path("todos/<int:pk>/peek/", views.todo_peek, name="todo_peek"),
    path("todos/<int:pk>/move/", views.todo_move, name="todo_move"),
    path("todos/<int:pk>/move-to/", views.todo_move_to, name="todo_move_to"),
    path("todos/<int:pk>/toggle/", views.todo_toggle, name="todo_toggle"),
    path("items/<int:pk>/subscription/", views.subscription, name="subscription"),
    path("items/<int:pk>/switch/", views.switch, name="switch"),
    path("items/<int:pk>/tick/", views.tick, name="item_tick"),
    path("items/<int:pk>/editing/", views.item_editing, name="item_editing"),
    path("items/<int:pk>/trash/", views.item_trash, name="item_trash"),
    path(
        "items/<int:pk>/move-to-project/",
        across.item_move_project,
        name="item_move_project",
    ),
    path("items/<int:pk>/restore/", views.item_restore, name="item_restore"),
]
