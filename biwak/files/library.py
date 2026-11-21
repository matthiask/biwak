"""Folders, docs and files (specs/files.md, stage 2)"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from biwak.files import attachments, operations, previews
from biwak.files.common import NotifyForm, comments_context, sidebar_context
from biwak.forms import Form
from biwak.items import editing, glance, operations as ops
from biwak.items.models import Item, Kind
from biwak.items.views import item_for
from biwak.modals import form_response
from biwak.permissions import staff_only
from biwak.projects.views import project_for


CONTAINED = [Kind.FOLDER, Kind.DOC, Kind.FILE]


def contents(user, project, folder):
    """What the person sees in the root (``folder`` None) or in a folder:
    folders first, then docs and files, by title"""
    return (
        glance
        .with_checklist(Item.objects.visible_to(user))
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
    if item is None or not item.parent_id:
        return []
    # Two queries however deep the folder is
    return list(Item.objects.ancestors(item))


def current_version(item):
    """A file's current version (the prefetched ones if there are)"""
    return item.upload.versions.all()[0]


def version_for(request, item, version_pk=None, *, deny=staff_only):
    """The file's current version, or the older one ``version_pk``: older
    versions can hold what was meant to be internal, also of files clients
    see now (like the history), so only staff get them (``deny`` raises
    for clients)"""
    if version_pk is None:
        return current_version(item)
    deny(request)
    return get_object_or_404(item.upload.versions, pk=version_pk)


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


class NewFolderForm(FolderForm):
    # Only folders at the top level have the switch (specs/access.md)
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)


def library(request, project, folder=None):
    # Folders, docs and files are created by staff (specs/access.md)
    can_create = ops.can_create(request.user, Kind.FOLDER)
    rows = list(contents(request.user, project, folder))
    versions = {
        row.pk: current_version(row)
        for row in Item.objects.filter(
            pk__in=[r.pk for r in rows if r.kind == Kind.FILE]
        ).prefetch_related("upload__versions")
    }
    for row in rows:
        row.version = versions.get(row.pk)
        row.can_move = ops.can_change(request.user, row)
    context = {
        "project": project,
        "folder": folder,
        "breadcrumbs": breadcrumbs(folder) + ([folder] if folder else []),
        "rows": rows,
        # ".." leads to the folder above, or the project's top level
        "up_url": (
            reverse("folder", args=[folder.parent_id])
            if folder and folder.parent_id
            else reverse("project_files", args=[project.pk])
        ),
        "can_create": can_create,
    }
    if folder is not None:
        context |= {"item": folder} | sidebar_context(request, folder)
        context["move_choices"] = folder_choices(request.user, project, exclude=folder)
    return render(request, "files/library.html", context)


def library_url(project, folder):
    if folder is not None:
        return folder.get_absolute_url()
    return reverse("project_files", args=[project.pk])


def folder_new(request, pk):
    """A new folder in the top level or ``?folder=``: a modal of the
    folder's page, also a page (specs/ui-round-7.md, part 2)"""
    project = project_for(request, pk)
    parent = folder_param(request, project)
    if not ops.can_create(request.user, Kind.FOLDER):
        raise PermissionDenied
    form = (FolderForm if parent else NewFolderForm)(request.POST or None)
    if form.is_valid():
        item = ops.create_folder(
            project=project,
            title=form.cleaned_data["title"],
            creator=request.user,
            parent=parent,
            visible=form.cleaned_data.get("visible", False),
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("New folder"),
        item=parent,
        project=project,
        cancel_url=library_url(project, parent),
        submit_label=_("Add folder"),
    )


def folder_rename(request, pk):
    """Renaming a folder: a modal of its "More" menu, also a page"""
    item = item_for(request, pk, Kind.FOLDER)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = FolderForm(request.POST or None, initial={"title": item.title})
    if form.is_valid():
        operations.update_folder(
            item, actor=request.user, title=form.cleaned_data["title"]
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("Rename…"),
        item=item,
        parent=item.parent,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Rename"),
    )


def project_files(request, pk):
    return library(request, project_for(request, pk))


def folder(request, pk):
    item = item_for(request, pk, Kind.FOLDER)
    return library(request, item.project, item)


class MoveForm(Form):
    """Where a folder, doc or file goes; the view checks the folder itself"""

    folder = forms.ChoiceField(label=_("Folder"), required=False)

    def __init__(self, *args, choices, current, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["folder"].choices = [
            ("", _("Project root")),
            *(
                (
                    str(target.pk),
                    path
                    + (
                        f" ({_('clients can see this')})"
                        if target.is_client_visible
                        else ""
                    ),
                )
                for target, path in choices
            ),
        ]
        self.initial["folder"] = str(current or "")


def item_move(request, pk):
    """Moves a folder, doc or file into a folder or (empty ``folder``) to
    the root: a modal on its page, also a page"""
    item = item_for(request, pk)
    if item.kind not in CONTAINED:
        raise PermissionDenied
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = MoveForm(
        request.POST or None,
        choices=folder_choices(request.user, item.project, exclude=item),
        current=item.parent_id,
    )
    if request.method == "POST":
        target = folder_param(request, item.project)
        try:
            ops.move_item(item, parent=target, actor=request.user)
        except ValueError:
            form.add_error(None, _("A folder can't be moved into itself."))
        else:
            return redirect(item)
    return form_response(
        request,
        form,
        title=_("Move to…"),
        item=item,
        parent=item.parent,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Move"),
    )


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
    base = request.POST.get("base") or editing.version(item)
    if form.is_valid():
        try:
            operations.update_upload(
                item,
                actor=request.user,
                base=request.POST.get("base"),
                **form.cleaned_data,
            )
        except editing.StaleEdit as exc:
            form.add_error(
                None,
                editing.stale_message(request.user, item.project, exc.who, exc.when),
            )
        else:
            return redirect(item)
    editing.start(item, request.user)
    return render(
        request,
        "files/file_form.html",
        {
            "project": item.project,
            "item": item,
            "form": form,
            "base": base,
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
    return attachments.serve(version_for(request, item, version_pk))


@require_GET
def file_preview(request, pk, version_pk=None):
    """A WebP thumbnail of images and PDFs, made on the first request"""
    item = item_for(request, pk, Kind.FILE)
    response = previews.serve(version_for(request, item, version_pk))
    if response is None:
        raise Http404("No preview")
    return response
