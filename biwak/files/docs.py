"""Docs: versions (specs/files.md, stage 2), edited live
(specs/collaboration.md)"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.activity.history import diff_lines
from biwak.collab import live
from biwak.files import operations, queries
from biwak.files.common import NotifyForm, comments_context, sidebar_context
from biwak.files.library import (
    breadcrumbs,
    folder_choices,
    folder_param,
)
from biwak.forms import Form
from biwak.items import operations as ops
from biwak.items.models import Kind
from biwak.items.views import item_for
from biwak.permissions import staff_only
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
    form.mention_fields(project, "title", "content", folder=folder)
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
    return {
        "item": item,
        "doc": doc,
        "breadcrumbs": breadcrumbs(item),
        "is_staff": not request.user.is_client,
        "can_edit": not doc.read_only and ops.can_change(request.user, item),
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


class TitleForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)


def doc_edit(request, pk):
    """The doc edited live: everybody who can see it opens the editor,
    those who can't change it (or a read-only doc) watch. Posting renames
    the doc or saves what's typed as a version."""
    item = item_for(request, pk, Kind.DOC)
    can_edit = live.access(request.user, item.pk) == live.WRITE
    form = TitleForm(request.POST or None, initial={"title": item.title})
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if request.POST.get("new_version"):
            operations.save_version(item, actor=request.user)
            messages.success(request, _("Saved as a version."))
            return redirect("doc_edit", item.pk)
        if form.is_valid():
            operations.update_doc(
                item, actor=request.user, title=form.cleaned_data["title"]
            )
            return redirect("doc_edit", item.pk)
    return render(
        request,
        "files/doc_live.html",
        {
            "project": item.project,
            "item": item,
            "form": form,
            "breadcrumbs": breadcrumbs(item),
            "can_edit": can_edit,
        },
    )


@require_POST
def doc_read_only(request, pk):
    """Staff make the doc read-only, or editable again"""
    item = item_for(request, pk, Kind.DOC)
    staff_only(request)
    operations.set_read_only(
        item, read_only=bool(request.POST.get("read_only")), actor=request.user
    )
    return redirect(item)


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
    versions = item.doc.versions.select_related("created_by")
    version = get_object_or_404(versions, pk=version_pk)
    before, is_latest = queries.neighbours(versions, version)
    return render(
        request,
        "files/doc_version.html",
        {
            "item": item,
            "breadcrumbs": breadcrumbs(item),
            "version": version,
            "before": before,
            "is_latest": is_latest,
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
    except operations.DocReadOnly:
        messages.error(request, _("The doc is read-only."))
    return redirect(item)
