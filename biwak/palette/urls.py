from django.urls import path

from biwak.palette import views


urlpatterns = [path("palette/", views.palette, name="palette")]
