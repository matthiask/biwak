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


@register.simple_tag
def file_url(file):
    """``{% file_url version %}``: where a page links or embeds a file
    (``file_urls.file_url()``: the storage's URL, presigned with a bucket);
    the page checked access already"""
    from biwak.files import file_urls

    return file_urls.file_url(file)


@register.simple_tag
def preview_url(version, fallback):
    """``{% preview_url version fallback %}``: the preview's storage URL
    once it was made, else ``fallback`` (the preview view, which makes it)"""
    from biwak.files import file_urls

    return file_urls.preview_url(version, fallback)
