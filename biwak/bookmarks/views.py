from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.bookmarks import operations as ops
from biwak.bookmarks.models import Bookmark, Link
from biwak.forms import Form, next_url
from biwak.items.views import item_for
from biwak.permissions import staff_only
from biwak.projects.views import project_for


def bookmarks(request):
    """The person's bookmarks, newest first, with what they point at now;
    those they can't see any more are hidden, not deleted"""
    found = Bookmark.objects.visible_to(request.user).select_related(
        "item", "item__project", "item__answer", "project"
    )
    return render(request, "bookmarks/bookmarks.html", {"bookmarks": found})


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
            "projects/_card_bookmark.html",
            {
                "project": project,
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
        help_text=_("Internal unless you switch it, also on items clients see."),
    )


def _create_link(request, *, project, item=None):
    staff_only(request)
    form = LinkForm(request.POST)
    target = (item or project).get_absolute_url()
    if form.is_valid():
        data = form.cleaned_data
        try:
            ops.add_link(
                project=project,
                item=item,
                url=data["url"],
                title=data["title"],
                visible=data["visible_to_clients"],
                created_by=request.user,
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    else:
        messages.error(
            request, " ".join(e for errors in form.errors.values() for e in errors)
        )
    return redirect(target)


@require_POST
def project_link_create(request, pk):
    return _create_link(request, project=project_for(request, pk))


@require_POST
def item_link_create(request, pk):
    item = item_for(request, pk)
    return _create_link(request, project=item.project, item=item)


def link_for(request, pk):
    return get_object_or_404(
        Link.objects.visible_to(request.user).select_related("project", "item"), pk=pk
    )


def link_edit(request, pk):
    link = link_for(request, pk)
    staff_only(request)
    target = (link.item or link.project).get_absolute_url()
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
    return render(
        request,
        "generic/form.html",
        {"form": form, "title": _("Edit the link"), "cancel": target},
    )


@require_POST
def link_delete(request, pk):
    link = link_for(request, pk)
    staff_only(request)
    target = (link.item or link.project).get_absolute_url()
    ops.delete_link(link)
    return redirect(target)


def _order(request, *, project, item=None):
    """The links in the dragged order (frontend/links.js); ``links`` are
    the IDs of all the links of the project or item the person sees"""
    staff_only(request)
    try:
        ids = [int(pk) for pk in request.POST.getlist("links")]
        ops.reorder_links(ids, user=request.user, project=project, item=item)
    except ValueError:
        return HttpResponse(status=400)
    return HttpResponse(status=204)


@require_POST
def project_link_order(request, pk):
    return _order(request, project=project_for(request, pk))


@require_POST
def item_link_order(request, pk):
    item = item_for(request, pk)
    return _order(request, project=item.project, item=item)
