from django.urls import path

from biwak.items import views


urlpatterns = [
    path("lists/<int:pk>/", views.todolist, name="list"),
    path("lists/<int:pk>/groups/", views.group_create, name="group_create"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("groups/<int:pk>/move/", views.group_move, name="group_move"),
    path("todos/<int:pk>/", views.todo, name="todo"),
    path("todos/<int:pk>/move/", views.todo_move, name="todo_move"),
    path("todos/<int:pk>/toggle/", views.todo_toggle, name="todo_toggle"),
    path("items/<int:pk>/subscription/", views.subscription, name="subscription"),
    path("items/<int:pk>/switch/", views.switch, name="switch"),
    path("items/<int:pk>/trash/", views.item_trash, name="item_trash"),
]
