from django.urls import path

from biwak.search import views


urlpatterns = [path("search/", views.search, name="search")]
