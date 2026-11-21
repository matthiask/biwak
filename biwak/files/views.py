from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from biwak.files import attachments
from biwak.files.models import Attachment
from biwak.projects.views import project_for


def attachment_json(attachment):
    return {
        "key": attachment.key,
        "name": attachment.name,
        "size": attachment.size,
        "content_type": attachment.content_type,
        "url": attachment.get_absolute_url(),
        "markdown": attachment.markdown,
    }


@require_POST
def attachment_upload(request, pk):
    """Dropping, pasting or attaching a file in a text field
    (frontend/attachments.js): the attachment and the Markdown to insert"""
    project = project_for(request, pk)
    if not (file := request.FILES.get("file")):
        return JsonResponse({"detail": _("No file.")}, status=400)
    try:
        attachment = attachments.upload(
            project=project, file=file, uploaded_by=request.user
        )
    except attachments.UploadError as exc:
        return JsonResponse({"detail": str(exc)}, status=413)
    return JsonResponse(attachment_json(attachment), status=201)


@require_GET
def attachment(request, key, name):
    """The download, if the person sees the attachment's item (or uploaded
    it and it has none yet), else 404; the name is only for people"""
    return attachments.serve(
        get_object_or_404(Attachment.objects.visible_to(request.user), key=key)
    )
