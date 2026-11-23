from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.bookmarks import operations as ops
from biwak.bookmarks.models import Bookmark, Link
from biwak.forms import Form, next_url
from biwak.items.views import item_for
from biwak.modals import form_response
from biwak.permissions import staff_only
from biwak.projects.views import project_for


def bookmarks(request):
    """The person's bookmarks, newest first, with what they point at now;
    those they can't see any more are hidden, not deleted"""
    found = Bookmark.objects.visible_to(request.user).select_related(
        "item", "item__project", "item__answer", "project"
    )
    # Bookmarked projects first (places to go to), then the items grouped
    # by project, the project with the newest bookmark first (decided
    # 2026-11-21: by project, not by kind)
    projects, groups = [], {}
    for bookmark in found:
        if bookmark.item_id is None:
            projects.append(bookmark)
        else:
            groups.setdefault(bookmark.item.project, []).append(bookmark)
    return render(
        request,
        "bookmarks/bookmarks.html",
        {"projects": projects, "groups": list(groups.items())},
    )


def _back(request, target):
    return redirect(next_url(request) or target)


@require_POST
def item_bookmark(request, pk):
    """Bookmarks (``bookmark=1``) or un-bookmarks the item"""
    item = item_for(request, pk)
    if request.POST.get("bookmark"):
        ops.add_bookmark(request.user, item=item)
    else:
        ops.remove_bookmark(request.user, item=item)
    return _back(request, item.get_absolute_url())


@require_POST
def project_bookmark(request, pk):
    project = project_for(request, pk)
    if request.POST.get("bookmark"):
        ops.add_bookmark(request.user, project=project)
    else:
        ops.remove_bookmark(request.user, project=project)
    if request.headers.get("HX-Request") and request.POST.get("card"):
        # The button on a card of the projects page swaps itself
        return render(
            request,
            "bookmarks/_bookmark_button.html",
            {
                "target": project,
                "card": True,
                "is_bookmarked": ops.is_bookmarked(request.user, project=project),
            },
        )
    return _back(request, project.get_absolute_url())


class LinkForm(Form):
    url = forms.URLField(label=_("URL"), max_length=2000, assume_scheme="https")
    title = forms.CharField(
        label=_("Title"),
        max_length=200,
        required=False,
        help_text=_("The address's host if empty."),
    )
    visible_to_clients = forms.BooleanField(
        label=_("Visible to clients"),
        required=False,
        help_text=_("Internal unless you switch it."),
    )


def project_link_new(request, pk):
    project = project_for(request, pk)
    staff_only(request)
    form = LinkForm(request.POST or None)
    if not project.offers_client_switch():
        # No clients, no switch (decided 2026-11-23, specs/access.md)
        del form.fields["visible_to_clients"]
    if form.is_valid():
        data = form.cleaned_data
        try:
            ops.add_link(
                project=project,
                url=data["url"],
                title=data["title"],
                visible=data.get("visible_to_clients", False),
                created_by=request.user,
            )
        except ValidationError as exc:
            form.add_error("url", exc)
        else:
            return redirect(project)
    return form_response(
        request,
        form,
        title=_("Add a link"),
        project=project,
        cancel_url=project.get_absolute_url(),
        submit_label=_("Add"),
    )


def link_for(request, pk):
    return get_object_or_404(
        Link.objects.visible_to(request.user).select_related("project"), pk=pk
    )


def link_edit(request, pk):
    link = link_for(request, pk)
    staff_only(request)
    target = link.project.get_absolute_url()
    form = LinkForm(
        request.POST or None,
        initial={
            "url": link.url,
            "title": link.title,
            "visible_to_clients": link.visible_to_clients,
        },
    )
    if form.is_valid():
        data = form.cleaned_data
        try:
            ops.update_link(
                link,
                url=data["url"],
                title=data["title"],
                visible=data["visible_to_clients"],
            )
        except ValidationError as exc:
            form.add_error("url", exc)
        else:
            return redirect(target)
    return form_response(
        request,
        form,
        title=_("Edit the link"),
        project=link.project,
        cancel_url=target,
    )


@require_POST
def link_delete(request, pk):
    link = link_for(request, pk)
    staff_only(request)
    target = link.project.get_absolute_url()
    ops.delete_link(link)
    return redirect(target)


@require_POST
def project_link_order(request, pk):
    """The links in the dragged order (frontend/sortable-order.js);
    ``links`` are the IDs of all the project's links the person sees"""
    project = project_for(request, pk)
    staff_only(request)
    try:
        ids = [int(pk) for pk in request.POST.getlist("links")]
        ops.reorder_links(ids, user=request.user, project=project)
    except ValueError:
        return HttpResponse(status=400)
    return HttpResponse(status=204)
