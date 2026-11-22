"""Docs: versions (specs/files.md, stage 2), edited live
(specs/collaboration.md)"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from biwak.activity.history import diff_lines
from biwak.activity.notify import told_line
from biwak.activity.views import SubscribersForm
from biwak.collab import live
from biwak.files import operations, queries
from biwak.files.common import comments_context, sidebar_context
from biwak.files.library import (
    breadcrumbs,
    folder_choices,
    folder_param,
    library_url,
)
from biwak.items import editing, operations as ops
from biwak.items.models import Kind
from biwak.items.views import item_for
from biwak.modals import form_response
from biwak.permissions import staff_only
from biwak.projects.views import project_for


# Docs -------------------------------------------------------------------


def doc_new(request, pk):
    """ "New doc": a draft opened in the editor at once, its text ``# ``
    with the cursor after it (specs/files.md, "Docs"). The address
    stays this one until the draft has text (frontend/collab.js puts the
    doc's into the history then); every visit makes a new draft, empty
    ones go after a day (``fairy_tasks``)."""
    project = project_for(request, pk)
    folder = folder_param(request, project)
    if not ops.can_create(request.user, Kind.DOC):
        raise PermissionDenied
    item = ops.create_draft(project=project, creator=request.user, parent=folder)
    return _editor(request, item)


def _doc_context(request, item):
    doc = item.doc
    return {
        "item": item,
        "doc": doc,
        "breadcrumbs": breadcrumbs(item),
        "is_staff": not request.user.is_client,
        "can_edit": not doc.read_only and ops.can_change(request.user, item),
        "move_choices": folder_choices(request.user, item.project, exclude=item),
        # Whoever has the doc open in the editor (no locks, specs/editor.md)
        "being_edited": editing.heads_up(
            request.user, item.project, editing.holders(item)
        ),
    } | sidebar_context(request, item)


def doc(request, pk):
    item = item_for(request, pk, Kind.DOC, drafts=True)
    if item.is_draft:
        # "Done" before writing anything: nothing to show
        return redirect(library_url(item.project, item.parent))
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
    """The doc edited live: everybody who can see it opens the editor,
    those who can't change it (or a read-only doc) watch. Posting saves
    what's typed as a version."""
    item = item_for(request, pk, Kind.DOC, drafts=True)
    if request.method == "POST":
        if live.access(request.user, item.pk) != live.WRITE:
            raise PermissionDenied
        operations.save_version(item, actor=request.user)
        messages.success(request, _("Saved as a version."))
        return redirect("doc_edit", item.pk)
    return _editor(request, item)


def _editor(request, item):
    """The live editor's page; a draft's creator is asked whom to tell at
    the first "Done" (``doc_tell``)"""
    return render(
        request,
        "files/doc_live.html",
        {
            "project": item.project,
            "item": item,
            "breadcrumbs": breadcrumbs(item),
            "can_edit": live.access(request.user, item.pk) == live.WRITE,
            "history": live.history(item.pk),
            "ask_to_tell": item.doc.tell_pending and item.creator_id == request.user.pk,
        },
    )


class TellForm(SubscribersForm):
    """ "Tell people about it?" (decided 2026-11-21, additive like posting,
    ``files.common.NotifyForm``): a line saying who is told by default
    (``default_told()``), "Also tell…" the subscribers' picker of the
    other members, nothing preselected, and the note"""

    def __init__(self, *args, item, user, **kwargs):
        super().__init__(*args, item=item, user=user, **kwargs)
        del self.fields["notify"]
        self.told = operations.default_told(item, user)
        field = self.fields["people"]
        field.label = _("Also tell…")
        field.required = False
        field.intro = told_line(self.told, item.project, user)
        # The project's members, as when posting (``NotifyForm``)
        field.queryset = field.queryset.filter(
            memberships__project=item.project
        ).exclude(pk__in=[u.pk for u in self.told])


@never_cache
def doc_tell(request, pk):
    """The first "Done" of a doc begun as a draft (specs/files.md, "Docs"): its
    creator is asked once whom to tell besides those told by default,
    "Tell them too" or "No one else" (only those), never again either way. A
    modal of the editor, also a page.
    What was typed is saved first; a draft still empty goes back to its
    folder."""
    item = item_for(request, pk, Kind.DOC, drafts=True)
    if item.creator_id != request.user.pk:
        return redirect(item)
    operations.save_live(item.pk, request.user)
    item.refresh_from_db()
    if item.is_draft:
        return redirect(library_url(item.project, item.parent))
    if not item.doc.tell_pending:
        return redirect(item)
    if request.method == "POST" and request.POST.get("not_now"):
        # Nobody else, but those who want to hear are told anyway
        # (decided 2026-11-21: additive)
        operations.tell(item, actor=request.user)
        return redirect(item)
    form = TellForm(request.POST or None, item=item, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        operations.tell(
            item, actor=request.user, also=data["people"], note=data["note"]
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("Tell people about it?"),
        intro=_("Nobody has heard of this doc yet. You're asked once."),
        item=item,
        cancel_url=item.get_absolute_url(),
        submit_label=_("Tell them too"),
        template="files/doc_tell.html",
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
