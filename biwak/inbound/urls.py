from django.urls import path

from biwak.inbound import views


urlpatterns = [
    path("inbound/resend/", views.resend, name="inbound_resend"),
]
