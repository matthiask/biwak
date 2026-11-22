"""Folders, docs and files (specs/files.md, stage 2)"""

import uuid

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _, ngettext
from django.views.decorators.http import require_GET, require_POST

from biwak.accounts.models import Color
from biwak.files import attachments, operations, previews
from biwak.files.common import NotifyForm, comments_context, sidebar_context
from biwak.files.queries import folder_counts
from biwak.forms import ColorSwatches, ComboboxSelect, Form, next_url
from biwak.items import editing, glance, operations as ops
from biwak.items.across import (
    NO_NOTES,
    Confirming,
    asking,
    confirmed_move,
    target_projects,
)
from biwak.items.models import Item, Kind
from biwak.items.views import item_for
from biwak.modals import form_response
from biwak.permissions import staff_only
from biwak.projects.models import FilesOrdering
from biwak.projects.views import project_for


CONTAINED = [Kind.FOLDER, Kind.DOC, Kind.FILE]


# The order of a folder's contents after its folders
ORDER_BY = {
    FilesOrdering.ALPHABETICAL: [Lower("title"), "pk"],
    FilesOrdering.REVERSE: [Lower("title").desc(), "-pk"],
    FilesOrdering.NEWEST: ["-created_at", "-pk"],
    FilesOrdering.OLDEST: ["created_at", "pk"],
}


def ordering_of(project, folder):
    """The order chosen for the folder, or for the project's top level"""
    return folder.folder.ordering if folder is not None else project.files_ordering


def contents(user, project, folder):
    """What the person sees in the root (``folder`` None) or in a folder:
    folders first, then docs and files, both in the folder's order"""
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
        .select_related("creator", "folder")
        .order_by("folder_first", *ORDER_BY[ordering_of(project, folder)])
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
    they see, not the item itself (or the items, a list) or what's in it"""
    folders = list(
        Item.objects
        .visible_to(user)
        .filter(project=project, kind=Kind.FOLDER)
        .select_related("parent")
        .order_by(Lower("title"))
    )
    by_pk = {f.pk: f for f in folders}
    skip = set()
    excluded = exclude if isinstance(exclude, list) else [exclude]
    for item in excluded:
        if item is not None and item.kind == Kind.FOLDER:
            skip |= {item.pk} | set(
                Item.objects.descendants(item).values_list("pk", flat=True)
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
    # None by default: folders aren't told apart unless somebody chooses
    # (specs/files.md, "Folder colors")
    color = forms.ChoiceField(
        label=_("color"),
        choices=[("", _("None")), *Color.choices],
        required=False,
        initial="",
        widget=ColorSwatches,
    )


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
    counts = folder_counts(request.user, [r for r in rows if r.kind == Kind.FOLDER])
    for row in rows:
        # The page's project, not one query per tile (its "More" menu asks
        # ``is_shareable``, which looks at the project)
        row.project = project
        row.version = versions.get(row.pk)
        row.counts = counts.get(row.pk)
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
    folder's page, also a page (specs/files.md, "Folders")"""
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
            color=form.cleaned_data["color"],
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


class OrderForm(Form):
    ordering = forms.ChoiceField(
        label=_("Order"), choices=FilesOrdering.choices, widget=forms.RadioSelect
    )


def _order(request, project, folder):
    """How a folder's contents (or the top level's) are ordered, for
    everybody; staff set it (specs/files.md, "Folders")"""
    staff_only(request)
    form = OrderForm(
        request.POST or None, initial={"ordering": ordering_of(project, folder)}
    )
    if form.is_valid():
        operations.set_ordering(
            folder or project, form.cleaned_data["ordering"], actor=request.user
        )
        return redirect(next_url(request) or library_url(project, folder))
    return form_response(
        request,
        form,
        title=_("Order…"),
        item=folder,
        project=project,
        cancel_url=next_url(request) or library_url(project, folder),
        intro=_("Folders come first, in the same order. Everybody sees it."),
    )


def folder_order(request, pk):
    item = item_for(request, pk, Kind.FOLDER)
    return _order(request, item.project, item)


def project_files_order(request, pk):
    return _order(request, project_for(request, pk), None)


def folder_edit(request, pk):
    """Renaming a folder and choosing its color: a modal of its "More"
    menu, also a page"""
    item = item_for(request, pk, Kind.FOLDER)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = FolderForm(
        request.POST or None, initial={"title": item.title, "color": item.folder.color}
    )
    if form.is_valid():
        operations.update_folder(
            item,
            actor=request.user,
            title=form.cleaned_data["title"],
            color=form.cleaned_data["color"],
        )
        return redirect(next_url(request) or item)
    return form_response(
        request,
        form,
        title=_("Edit…"),
        item=item,
        parent=item.parent,
        cancel_url=next_url(request) or item.get_absolute_url(),
        submit_label=_("Save"),
    )


def project_files(request, pk):
    return library(request, project_for(request, pk))


def folder(request, pk):
    item = item_for(request, pk, Kind.FOLDER)
    return library(request, item.project, item)


class MoveForm(Confirming):
    """Where a folder, doc or file goes; the view checks the folder itself.
    With ``projects``, the top of other projects too
    (specs/lists-across-projects.md), as ``project:<pk>``."""

    folder = forms.ChoiceField(label=_("Folder"), required=False)

    def __init__(self, *args, choices, current, projects=(), **kwargs):
        super().__init__(*args, **kwargs)
        folders = [
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
        field = self.fields["folder"]
        if projects:
            field.label = _("Folder or project")
            field.widget = ComboboxSelect()
            field.choices = [
                (_("This project"), folders),
                (
                    _("Other projects"),
                    [(f"project:{p.pk}", p.name) for p in projects],
                ),
            ]
        else:
            field.choices = folders
        self.initial["folder"] = str(current or "")


def item_move(request, pk):
    """Moves a folder, doc or file into a folder or (empty ``folder``) to
    the root: a modal on its page, also a page"""
    item = item_for(request, pk)
    if item.kind not in CONTAINED:
        raise PermissionDenied
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    projects = list(target_projects(request.user, item))
    form = MoveForm(
        request.POST or None,
        choices=folder_choices(request.user, item.project, exclude=item),
        current=item.parent_id,
        projects=projects,
    )
    notes = NO_NOTES
    value = request.POST.get("folder", "")
    if request.method == "POST" and value.startswith("project:"):
        # To the top of another project (specs/lists-across-projects.md)
        if form.is_valid():
            project = next(p for p in projects if f"project:{p.pk}" == value)
            response, notes = confirmed_move(request, item, project, form)
            if response is not None:
                # To the item in its new project, not back to the old one
                return response
    elif request.method == "POST":
        target = folder_param(request, item.project)
        try:
            ops.move_item(item, parent=target, actor=request.user)
        except ValueError:
            form.add_error(None, _("A folder can't be moved into itself."))
        else:
            return redirect(next_url(request) or item)
    return asking(
        request,
        form,
        title=_("Move to…"),
        item=item,
        notes=notes,
        cancel_url=next_url(request) or item.get_absolute_url(),
        submit_label=_("Move"),
    )


def selected(request, project):
    """The folders, docs and files of a selection (``items``, posted or in
    the query): those the person sees in the project (else 404), and may
    move or trash (else 403), as with "Move to…" one by one"""
    pks = request.POST.getlist("items") or request.GET.getlist("items")
    if not pks or not all(pk.isdecimal() for pk in pks):
        raise Http404
    items = list(
        Item.objects
        .visible_to(request.user)
        .filter(project=project, kind__in=CONTAINED, pk__in=pks)
        .select_related("parent", "creator")
        .order_by(Lower("title"), "pk")
    )
    if len(items) != len(set(pks)):
        raise Http404
    if not all(ops.can_change(request.user, item) for item in items):
        raise PermissionDenied
    return items


def _selection_title(items):
    if len(items) == 1:
        return items[0].shown_title
    return ngettext("%(count)s item", "%(count)s items", len(items)) % {
        "count": len(items)
    }


def files_move(request, pk):
    """Moves several folders, docs and files at once (the selection's
    "Move to…", a modal, also a page; dropping them onto a folder posts
    here with ``folder``) with the operation of "Move to…"
    (specs/files.md, "Moving and selecting")"""
    project = project_for(request, pk)
    items = selected(request, project)
    current = items[0].parent
    form = MoveForm(
        request.POST or None,
        choices=folder_choices(request.user, project, exclude=items),
        current=current.pk if current else None,
    )
    if request.method == "POST":
        target = folder_param(request, project)
        try:
            operations.move_items(items, parent=target, actor=request.user)
        except ValueError:
            form.add_error(None, _("A folder can't be moved into itself."))
        else:
            return redirect(library_url(project, current))
    return form_response(
        request,
        form,
        title=_("Move to…"),
        intro=_selection_title(items),
        project=project,
        cancel_url=library_url(project, current),
        submit_label=_("Move"),
    )


def files_trash(request, pk):
    """Moves several folders, docs and files to the trash: asks first (a
    modal, also a page), the POST does it"""
    project = project_for(request, pk)
    items = selected(request, project)
    current = items[0].parent
    if request.method != "POST":
        return form_response(
            request,
            None,
            title=_("Move to the trash?"),
            intro=(
                _("“%(title)s” can be restored for %(days)s days.")
                if len(items) == 1
                else _("%(count)s items can be restored for %(days)s days.")
            )
            % {
                "title": items[0].shown_title,
                "count": len(items),
                "days": ops.TRASH_DAYS,
            },
            project=project,
            cancel_url=library_url(project, current),
            submit_label=_("Move to the trash"),
            destructive=True,
        )
    operations.trash_items(items, actor=request.user)
    messages.success(
        request,
        (
            _("“%(title)s” is in the trash for %(days)s days.")
            if len(items) == 1
            else _("%(count)s items are in the trash for %(days)s days.")
        )
        % {"title": items[0].shown_title, "count": len(items), "days": ops.TRASH_DAYS},
    )
    return redirect(library_url(project, current))


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


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files from one input; ``cleaned_data`` is a list"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, list | tuple):
            if not data and self.required:
                raise forms.ValidationError(self.error_messages["required"])
            return [super(MultipleFileField, self).clean(one, initial) for one in data]
        return [super().clean(data, initial)]


class UploadSettingsForm(NotifyForm, Form):
    """What all files of an upload share: whom to notify, and at the top
    level whether clients see them (in a folder they follow the folder)"""

    visible = forms.BooleanField(label=_("Visible to clients"), required=False)
    field_order = ["files", "visible", "notify", "people"]

    def __init__(self, *args, folder=None, **kwargs):
        super().__init__(*args, folder=folder, **kwargs)
        if folder is not None:
            del self.fields["visible"]


class UploadFilesForm(UploadSettingsForm):
    files = MultipleFileField(label=_("Files"))
    # frontend/upload.js empties the input, keeping the files in its list
    use_required_attribute = False


class UploadOneForm(UploadSettingsForm):
    """One file of an upload from the modal (frontend/upload.js): its
    title (the name without its extension changed) and the batch"""

    file = forms.FileField(label=_("file"))
    title = forms.CharField(label=_("name"), max_length=500, required=False)
    batch = forms.RegexField(regex=r"^[0-9a-f]{32}$")
    # More files of the batch follow this one: its mail waits for them
    more = forms.BooleanField(required=False)


def keep_extension(title, name):
    """The title given for a file, with the file name's extension kept"""
    title = (title or "").strip()
    if not title:
        return name
    _stem, dot, extension = name.rpartition(".")
    if dot and _stem and not title.lower().endswith(f".{extension.lower()}"):
        return f"{title}.{extension}"
    return title


def _uploads(request, project, folder, form, files, *, batch):
    """Creates the files (one ``batch``), each with the operation of the
    single upload; returns the items and the errors ``[(name, error)]``"""
    data = form.cleaned_data
    created, errors = [], []
    for file, title in files:
        try:
            created.append(
                ops.create_upload(
                    project=project,
                    file=file,
                    title=keep_extension(title, attachments.clean_name(file.name)),
                    creator=request.user,
                    parent=folder,
                    visible=data.get("visible", False),
                    also=form.also_people(),
                    batch=batch,
                    more=data.get("more", False),
                )
            )
        except attachments.UploadError as exc:
            errors.append((file.name, str(exc)))
    return created, errors


def file_new(request, pk):
    """ "Upload files": a modal on the folder's page (frontend/upload.js
    sends the files one by one to ``file_upload``), also a page with a
    file input taking several (specs/files.md, "Uploading files")"""
    project = project_for(request, pk)
    folder = folder_param(request, project)
    if not ops.can_create(request.user, Kind.FILE):
        raise PermissionDenied
    form = UploadFilesForm(
        request.POST or None,
        request.FILES or None,
        project=project,
        user=request.user,
        folder=folder,
    )
    if form.is_valid():
        files = [(file, "") for file in form.cleaned_data["files"]]
        created, errors = _uploads(
            request, project, folder, form, files, batch=uuid.uuid4().hex
        )
        for name, error in errors:
            messages.error(request, f"{name}: {error}")
        if len(created) == 1 and not errors:
            return redirect(created[0])
        if created or not errors:
            return redirect(library_url(project, folder))
        form.add_error("files", [error for _name, error in errors])
    return form_response(
        request,
        form,
        title=_("Upload files"),
        item=folder,
        project=project,
        cancel_url=library_url(project, folder),
        submit_label=_("Upload"),
        multipart=True,
        template="files/upload_form.html",
        extra={
            "folder": folder,
            "batch": uuid.uuid4().hex,
            "upload_url": reverse("file_upload", args=[project.pk])
            + (f"?folder={folder.pk}" if folder else ""),
            "done_url": library_url(project, folder),
            "max_size": attachments.MAX_SIZE,
        },
    )


@require_POST
def file_upload(request, pk):
    """One file of the modal's upload, as JSON: 201 with the file, else
    the errors (413 for a file over the limit)"""
    project = project_for(request, pk)
    folder = folder_param(request, project)
    if not ops.can_create(request.user, Kind.FILE):
        raise PermissionDenied
    form = UploadOneForm(
        request.POST, request.FILES, project=project, user=request.user, folder=folder
    )
    if not form.is_valid():
        return JsonResponse(
            {
                "detail": " ".join(
                    str(error) for errors in form.errors.values() for error in errors
                )
            },
            status=400,
        )
    data = form.cleaned_data
    created, errors = _uploads(
        request, project, folder, form, [(data["file"], data["title"])],
        batch=data["batch"],
    )  # fmt: skip
    if errors:
        return JsonResponse({"detail": errors[0][1]}, status=413)
    item = created[0]
    return JsonResponse(
        {"id": item.pk, "title": item.title, "url": item.get_absolute_url()},
        status=201,
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
