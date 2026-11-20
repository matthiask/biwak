"""Previews of images and PDFs (specs/files.md, stage 2)

A WebP thumbnail 400 pixels wide (images smaller than that keep their
size), made on the first request and stored next to the file
(``files/<project>/<key>/preview.webp``). PDFs show their first page
(pypdfium2, no system packages). Like downloads, previews are only served
after the visibility check.
"""

import io
import logging
import threading

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from biwak.files import attachments
from biwak.files.models import preview_name


logger = logging.getLogger(__name__)

WIDTH = 400

# pdfium isn't thread safe
_pdfium = threading.Lock()


def _image(version):
    with version.file.storage.open(version.file.name, "rb") as file:
        image = Image.open(file)
        image.load()
    return ImageOps.exif_transpose(image)


def _pdf_page(version):
    import pypdfium2

    with version.file.storage.open(version.file.name, "rb") as file:
        data = file.read()
    with _pdfium:
        pdf = pypdfium2.PdfDocument(data)
        try:
            page = pdf[0]
            scale = WIDTH / max(page.get_width(), 1)
            return page.render(scale=scale).to_pil()
        finally:
            pdf.close()


def _webp(image):
    if image.width > WIDTH:
        image = image.resize((WIDTH, max(1, round(image.height * WIDTH / image.width))))
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    out = io.BytesIO()
    image.save(out, "WEBP", quality=80)
    return out.getvalue()


def render(version):
    """The preview's WebP bytes, or None if the file can't be shown"""
    load = _pdf_page if version.content_type == "application/pdf" else _image
    try:
        return _webp(load(version))
    except Exception:  # broken or exotic files: no preview, not an error
        logger.warning("No preview for file version %s", version.pk, exc_info=True)
        return None


def preview_for(version):
    """The storage name of the version's preview, made if it doesn't exist
    yet; None for files without one"""
    if not version.has_preview:
        return None
    storage = version.file.storage
    name = preview_name(version.file.name)
    if storage.exists(name):
        return name
    data = render(version)
    if data is None:
        return None
    return storage.save(name, ContentFile(data))


def serve(version):
    """The preview as a response (a redirect with a bucket), or None"""
    if (name := preview_for(version)) is None:
        return None
    return attachments.respond(
        version.file.storage,
        name,
        content_type="image/webp",
        filename="preview.webp",
        as_attachment=False,
    )
