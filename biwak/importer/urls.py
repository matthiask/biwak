from django.urls import path

from biwak.importer import views


urlpatterns = [
    path("basecamp/", views.basecamp_link, name="basecamp_link"),
]
