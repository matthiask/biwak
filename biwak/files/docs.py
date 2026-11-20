"""Docs: versions and locks (specs/files.md, stage 2)"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.activity.history import diff_lines
from biwak.files import operations
from biwak.files.common import NotifyForm, comments_context, sidebar_context
from biwak.files.library import (
    breadcrumbs,
    folder_choices,
    folder_param,
    staff_only,
)
from biwak.forms import Form
from biwak.items import operations as ops
from biwak.items.models import Kind
from biwak.items.views import item_for
from biwak.projects.views import project_for


# Docs -------------------------------------------------------------------


class DocForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    content = forms.CharField(
        label=_("content"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 20}),
        help_text=_("Markdown"),
    )


class NewDocForm(NotifyForm, DocForm):
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)
    field_order = ["title", "content", "visible", "notify", "people"]


def doc_new(request, pk):
    project = project_for(request, pk)
    folder = folder_param(request, project)
    if not ops.can_create(request.user, Kind.DOC):
        raise PermissionDenied
    form = NewDocForm(request.POST or None, project=project)
    if form.is_valid():
        data = form.cleaned_data
        item = ops.create_doc(
            project=project,
            title=data["title"],
            content=data["content"],
            creator=request.user,
            parent=folder,
            visible=data["visible"],
            whom=form.whom(),
        )
        return redirect(item)
    return render(
        request,
        "files/doc_form.html",
        {
            "project": project,
            "folder": folder,
            "breadcrumbs": breadcrumbs(folder) + ([folder] if folder else []),
            "form": form,
            "item": None,
        },
    )


def _doc_context(request, item):
    doc = item.doc
    holder = operations.lock_holder(doc)
    return {
        "item": item,
        "doc": doc,
        "breadcrumbs": breadcrumbs(item),
        "locked_by": holder if holder != request.user else None,
        "is_staff": not request.user.is_client,
        "can_change": ops.can_change(request.user, item),
        "move_choices": folder_choices(request.user, item.project, exclude=item),
    } | sidebar_context(request, item)


def doc(request, pk):
    item = item_for(request, pk, Kind.DOC)
    comment_form, done = comments_context(request, item)
    if done:
        return done
    return render(
        request,
        "files/doc.html",
        _doc_context(request, item)
        | {
            "comment_form": comment_form,
            "comments": item.comments.select_related("author"),
        },
    )


def doc_edit(request, pk):
    """Opening the form takes the lock; saving over somebody else's newer
    version is refused. Clients only edit docs they created."""
    item = item_for(request, pk, Kind.DOC)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    doc = item.doc
    mentions_url = reverse("mentionable", args=[item.pk])
    if request.method != "POST":
        try:
            operations.lock_doc(item, request.user)
        except operations.DocLocked as exc:
            messages.warning(
                request,
                _("%(name)s is editing this doc. You can read it meanwhile.")
                % {"name": exc.user.get_short_name()},
            )
            return redirect(item)
    latest = doc.versions.first()
    form = DocForm(
        request.POST or None,
        initial={"title": item.title, "content": doc.content},
    )
    for name in ["title", "content"]:
        form.fields[name].widget.attrs["data-mentions"] = mentions_url
    conflict = None
    if form.is_valid():
        try:
            operations.update_doc(
                item,
                actor=request.user,
                new_version=bool(request.POST.get("new_version")),
                base_version=_int(request.POST.get("base_version")),
                **form.cleaned_data,
            )
        except operations.DocConflict as exc:
            conflict = exc.version
        except operations.DocLocked as exc:
            form.add_error(
                None,
                _("%(name)s is editing this doc.")
                % {"name": exc.user.get_short_name()},
            )
        else:
            return redirect(item)
    return render(
        request,
        "files/doc_form.html",
        {
            "project": item.project,
            "item": item,
            "form": form,
            "breadcrumbs": breadcrumbs(item),
            "base_version": request.POST.get("base_version") or (latest and latest.pk),
            "conflict": conflict,
            "is_staff": not request.user.is_client,
        },
    )


def _int(value):
    try:
        return int(value)
    except TypeError, ValueError:
        return None


@require_POST
def doc_lock(request, pk):
    """The edit page renews the lock every minute (frontend/doc-lock.js);
    ``release`` gives it up (Cancel)"""
    item = item_for(request, pk, Kind.DOC)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    if request.POST.get("release"):
        operations.unlock_doc(item, request.user)
        return redirect(item)
    try:
        operations.lock_doc(item, request.user)
    except operations.DocLocked as exc:
        return JsonResponse({"locked_by": exc.user.get_short_name()}, status=409)
    return HttpResponse(status=204)


def doc_versions(request, pk):
    item = item_for(request, pk, Kind.DOC)
    staff_only(request)
    return render(
        request,
        "files/doc_versions.html",
        {
            "item": item,
            "breadcrumbs": breadcrumbs(item),
            "versions": item.doc.versions.select_related("created_by"),
        },
    )


def doc_version(request, pk, version_pk):
    """An older version with what changed since the one before it"""
    item = item_for(request, pk, Kind.DOC)
    staff_only(request)
    versions = list(item.doc.versions.select_related("created_by"))
    index = next((i for i, v in enumerate(versions) if v.pk == version_pk), None)
    if index is None:
        return HttpResponse(status=404)
    version = versions[index]
    before = versions[index + 1] if index + 1 < len(versions) else None
    return render(
        request,
        "files/doc_version.html",
        {
            "item": item,
            "breadcrumbs": breadcrumbs(item),
            "version": version,
            "before": before,
            "is_latest": index == 0,
            "diff": diff_lines(before.content if before else "", version.content),
        },
    )


@require_POST
def doc_version_restore(request, pk, version_pk):
    item = item_for(request, pk, Kind.DOC)
    staff_only(request)
    version = get_object_or_404(item.doc.versions, pk=version_pk)
    try:
        operations.restore_doc_version(item, version, actor=request.user)
    except operations.DocLocked as exc:
        messages.error(
            request,
            _("%(name)s is editing this doc.") % {"name": exc.user.get_short_name()},
        )
    return redirect(item)
