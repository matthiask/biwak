"""Folders, docs and files (specs/files.md, stage 2)"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from biwak.files import attachments, operations, previews
from biwak.files.common import NotifyForm, comments_context, sidebar_context
from biwak.forms import Form
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.items.views import item_for
from biwak.projects.views import project_for


CONTAINED = [Kind.FOLDER, Kind.DOC, Kind.FILE]


def contents(user, project, folder):
    """What the person sees in the root (``folder`` None) or in a folder:
    folders first, then docs and files, by title"""
    return (
        Item.objects
        .visible_to(user)
        .filter(project=project, parent=folder, kind__in=CONTAINED)
        .annotate(
            folder_first=Case(
                When(kind=Kind.FOLDER, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .select_related("creator")
        .order_by("folder_first", Lower("title"), "pk")
    )


def breadcrumbs(item):
    """The folders above ``item``, the top one first"""
    chain = []
    while item is not None and item.parent_id:
        item = item.parent
        chain.append(item)
    return chain[::-1]


def current_version(item):
    """A file's current version (the prefetched ones if there are)"""
    return item.upload.versions.all()[0]


def folder_choices(user, project, *, exclude=None):
    """The folders a person can move something to, as (item, path): those
    they see, not the item itself or what's in it"""
    folders = list(
        Item.objects
        .visible_to(user)
        .filter(project=project, kind=Kind.FOLDER)
        .select_related("parent")
        .order_by(Lower("title"))
    )
    by_pk = {f.pk: f for f in folders}
    skip = set()
    if exclude is not None and exclude.kind == Kind.FOLDER:
        skip = {exclude.pk} | set(
            Item.objects.descendants(exclude).values_list("pk", flat=True)
        )

    def path(folder):
        parts = [folder.title]
        while folder.parent_id in by_pk:
            folder = by_pk[folder.parent_id]
            parts.append(folder.title)
        return " / ".join(reversed(parts))

    choices = [(f, path(f)) for f in folders if f.pk not in skip]
    return sorted(choices, key=lambda choice: choice[1].lower())


class FolderForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)


def library(request, project, folder=None):
    # Folders, docs and files are created by staff (specs/access.md)
    can_create = ops.can_create(request.user, Kind.FOLDER)
    if request.method == "POST" and not can_create:
        raise PermissionDenied
    form = FolderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = ops.create_folder(
            project=project,
            title=form.cleaned_data["title"],
            creator=request.user,
            parent=folder,
            visible=bool(request.POST.get("visible")),
        )
        return redirect(item)
    rows = list(contents(request.user, project, folder))
    versions = {
        row.pk: current_version(row)
        for row in Item.objects.filter(
            pk__in=[r.pk for r in rows if r.kind == Kind.FILE]
        ).prefetch_related("upload__versions")
    }
    for row in rows:
        row.version = versions.get(row.pk)
    context = {
        "project": project,
        "folder": folder,
        "breadcrumbs": breadcrumbs(folder) + ([folder] if folder else []),
        "rows": rows,
        "form": form,
        "can_create": can_create,
        "can_create_switch": folder is None and can_create,
    }
    if folder is not None:
        context |= {"item": folder} | sidebar_context(request, folder)
        context["move_choices"] = folder_choices(request.user, project, exclude=folder)
    return render(request, "files/library.html", context)


def project_files(request, pk):
    return library(request, project_for(request, pk))


def folder(request, pk):
    item = item_for(request, pk, Kind.FOLDER)
    return library(request, item.project, item)


@require_POST
def item_move(request, pk):
    """Moves a folder, doc or file into a folder or (empty ``folder``) to
    the root"""
    item = item_for(request, pk)
    if item.kind not in CONTAINED:
        raise PermissionDenied
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    target = None
    if target_pk := request.POST.get("folder"):
        target = item_for(request, target_pk, Kind.FOLDER)
        if target.project_id != item.project_id:
            return HttpResponse(status=404)
    try:
        ops.move_item(item, parent=target, actor=request.user)
    except ValueError:
        messages.error(request, _("A folder can't be moved into itself."))
    return redirect(item)


def folder_param(request, project):
    """The folder a new doc or file goes to (``?folder=``, ``folder`` of
    the form): one the person sees, or the root"""
    if pk := request.POST.get("folder") or request.GET.get("folder"):
        if not pk.isdecimal():
            raise Http404
        folder = item_for(request, pk, Kind.FOLDER)
        if folder.project_id != project.pk:
            raise Http404
        return folder
    return None


def staff_only(request):
    """Older versions can hold what was meant to be internal, also of docs
    and files clients see now (like the history): staff only"""
    if request.user.is_client:
        raise PermissionDenied


# Files ------------------------------------------------------------------


class UploadForm(Form):
    file = forms.FileField(label=_("file"))


class NewFileForm(NotifyForm, Form):
    file = forms.FileField(label=_("file"))
    description = forms.CharField(
        label=_("description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Markdown"),
    )
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)
    field_order = ["file", "description", "visible", "notify", "people"]


def file_new(request, pk):
    project = project_for(request, pk)
    folder = folder_param(request, project)
    if not ops.can_create(request.user, Kind.FILE):
        raise PermissionDenied
    form = NewFileForm(request.POST or None, request.FILES or None, project=project)
    form.mention_fields(project, "description", folder=folder)
    if form.is_valid():
        data = form.cleaned_data
        try:
            item = ops.create_upload(
                project=project,
                file=data["file"],
                description=data["description"],
                creator=request.user,
                parent=folder,
                visible=data["visible"],
                whom=form.whom(),
            )
        except attachments.UploadError as exc:
            form.add_error("file", str(exc))
        else:
            return redirect(item)
    return render(
        request,
        "files/file_form.html",
        {
            "project": project,
            "folder": folder,
            "breadcrumbs": breadcrumbs(folder) + ([folder] if folder else []),
            "form": form,
            "item": None,
        },
    )


def file(request, pk):
    item = item_for(request, pk, Kind.FILE)
    comment_form, done = comments_context(request, item)
    if done:
        return done
    upload = item.upload
    versions = list(upload.versions.select_related("uploaded_by"))
    staff = not request.user.is_client
    return render(
        request,
        "files/file.html",
        {
            "item": item,
            "upload": upload,
            "version": versions[0],
            # Older versions are for staff (see staff_only)
            "older_versions": versions[1:] if staff else [],
            "breadcrumbs": breadcrumbs(item),
            "comment_form": comment_form,
            "comments": item.comments.select_related("author"),
            "replace_form": UploadForm(),
            "move_choices": folder_choices(request.user, item.project, exclude=item),
        }
        | sidebar_context(request, item),
    )


class FileEditForm(Form):
    title = forms.CharField(label=_("name"), max_length=500)
    description = forms.CharField(
        label=_("description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=_("Markdown"),
    )


def file_edit(request, pk):
    item = item_for(request, pk, Kind.FILE)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = FileEditForm(
        request.POST or None,
        initial={"title": item.title, "description": item.upload.description},
    )
    mentions_url = reverse("mentionable", args=[item.pk])
    for name in ["title", "description"]:
        form.fields[name].widget.attrs["data-mentions"] = mentions_url
    if form.is_valid():
        operations.update_upload(item, actor=request.user, **form.cleaned_data)
        return redirect(item)
    return render(
        request,
        "files/file_form.html",
        {
            "project": item.project,
            "item": item,
            "form": form,
            "breadcrumbs": breadcrumbs(item),
        },
    )


@require_POST
def file_replace(request, pk):
    """A new version: the URL, comments and earlier versions stay"""
    item = item_for(request, pk, Kind.FILE)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, _("Choose a file."))
        return redirect(item)
    try:
        operations.replace_upload(item, form.cleaned_data["file"], actor=request.user)
    except attachments.UploadError as exc:
        messages.error(request, str(exc))
    return redirect(item)


@require_GET
def file_download(request, pk, version_pk=None):
    """The current version; older ones (staff) by ``version_pk``. Visible
    exactly when the file's item is, else 404."""
    item = item_for(request, pk, Kind.FILE)
    versions = item.upload.versions.all()
    if version_pk is None:
        version = versions[0]
    else:
        staff_only(request)
        version = get_object_or_404(versions, pk=version_pk)
    return attachments.serve(version)


@require_GET
def file_preview(request, pk, version_pk=None):
    """A WebP thumbnail of images and PDFs, made on the first request"""
    item = item_for(request, pk, Kind.FILE)
    versions = item.upload.versions.all()
    if version_pk is None:
        version = versions[0]
    else:
        staff_only(request)
        version = get_object_or_404(versions, pk=version_pk)
    response = previews.serve(version)
    if response is None:
        return HttpResponse(status=404)
    return response
