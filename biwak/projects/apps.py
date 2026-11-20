from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ProjectsConfig(AppConfig):
    name = "biwak.projects"
    verbose_name = _("projects")
