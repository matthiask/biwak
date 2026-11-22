from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext

from biwak.files.models import MAX_SIZE


register = template.Library()


@register.simple_tag
def attachments_attrs(project):
    """The attributes of a form whose text fields take attachments
    (frontend/attachments.js); with files/_attach_button.html inside"""
    return format_html(
        'data-attachments="{}" data-attachments-max="{}"'
        ' data-attachments-too-large="{}" data-attachments-uploading="{}"'
        ' data-attachments-failed="{}"',
        reverse("attachment_upload", kwargs={"pk": project.pk}),
        MAX_SIZE,
        gettext("Files can be at most %(size)s MB.") % {"size": MAX_SIZE // 2**20},
        # The scripts put in the name (specs/languages.md: words in any order)
        gettext("Uploading %(name)s…"),
        gettext("Not uploaded, please try again."),
    )
