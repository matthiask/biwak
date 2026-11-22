"""Public links (specs/public-links.md): the "Share…" modal, the page of all
public links and the public page itself, which needs no sign-in"""

from django import forms
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _, ngettext_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from biwak.files import attachments, previews
from biwak.files.models import Attachment
from biwak.forms import Form, next_url
from biwak.items.models import Kind
from biwak.items.operations import text_of
from biwak.items.views import item_for
from biwak.modals import form_response, is_modal
from biwak.public_links import operations as ops
from biwak.public_links.models import DAYS, DEFAULT_DAYS, PublicLink


class ShareForm(Form):
    days = forms.TypedChoiceField(
        label=_("Expires after"),
        coerce=int,
        choices=[
            (
                days,
                ngettext_lazy("%(days)s day", "%(days)s days", days) % {"days": days},
            )
            for days in DAYS
        ],
        initial=DEFAULT_DAYS,
    )


def _shareable(request, pk):
    """The item, if the person may share it: 404 for what they can't see
    and for containers, 403 for clients"""
    item = item_for(request, pk)
    if request.user.is_client:
        raise PermissionDenied
    if not item.is_shareable:
        raise Http404
    return item


def _share_page(request, item, form, *, created=False):
    link = PublicLink.objects.filter(item=item).first()
    return form_response(
        request,
        form,
        title=_("Share “%(title)s”") % {"title": item.title},
        item=item,
        cancel_url=next_url(request) or item.get_absolute_url(),
        help_page="clients",
        submit_label=_("Create public link"),
        destructive=True,
        template="public_links/share.html",
        extra={
            "own_url": request.build_absolute_uri(item.get_absolute_url()),
            "link": link,
            "public_url": request.build_absolute_uri(link.get_absolute_url())
            if link
            else "",
            "created": created,
        },
    )


@never_cache
def item_share(request, pk):
    """Share…: the item's own link first, then its public link (with Copy,
    its expiry and Stop sharing) or creating one; a POST with ``stop``
    stops it. In the modal the answer is the modal again, showing the new
    link; the page redirects to itself."""
    item = _shareable(request, pk)
    if request.method == "POST":
        if request.POST.get("stop"):
            ops.stop_public_link(item, actor=request.user)
            form = ShareForm()
        else:
            form = ShareForm(request.POST)
            if not form.is_valid():
                return _share_page(request, item, form)
            ops.create_public_link(
                item, days=form.cleaned_data["days"], actor=request.user
            )
        if not is_modal(request):
            return redirect(request.get_full_path())
        return _share_page(
            request, item, ShareForm(), created=not request.POST.get("stop")
        )
    return _share_page(request, item, ShareForm())


@never_cache
def public_links(request):
    """All live public links in the projects the person can open (admins:
    all of them), the soonest expiry first; clients get 404"""
    if request.user.is_client:
        raise Http404
    links = PublicLink.objects.listed_for(request.user).select_related(
        "item", "item__project", "item__answer", "created_by"
    )
    return render(
        request,
        "public_links/list.html",
        {
            "links": [
                (link, request.build_absolute_uri(link.get_absolute_url()))
                for link in links
            ]
        },
    )


@require_POST
def public_link_stop(request, pk):
    """Stop sharing on the page of all public links: no question, stopping
    is safe; htmx takes the list out of the page it redirects to"""
    link = get_object_or_404(PublicLink.objects.listed_for(request.user), pk=pk)
    ops.stop_public_link(link.item, actor=request.user)
    return redirect("public_links")


# The public page -----------------------------------------------------------


def _open(token):
    """The link if its page may be shown now, else 404: the same whether
    the token never existed, expired or was stopped, or its item is gone"""
    if (link := PublicLink.objects.open(token)) is None:
        raise Http404
    return link


def _private(response):
    """Not indexed, no referrer sent on, not cached"""
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "private, no-store"
    return response


@login_not_required
@require_GET
def public_page(request, token):
    """One item, read only, without sign-in: its title, its text (no
    ticking), its attachments, the file itself, the author and the date;
    nothing else of the app (decided 2026-11-22)"""
    link = _open(token)
    item = link.item
    text = text_of(item)
    version = None
    if item.kind == Kind.FILE:
        version = item.upload.versions.all()[0]
    return _private(
        render(
            request,
            "public_links/public.html",
            {
                "link": link,
                "item": item,
                "text": text,
                "version": version,
            },
        )
    )


@login_not_required
@require_GET
def public_attachment(request, token, key, name):
    """An attachment of the item's text, through the token"""
    link = _open(token)
    attachment = get_object_or_404(Attachment, key=key, item=link.item)
    return _private(attachments.serve(attachment))


@login_not_required
@require_GET
def public_download(request, token):
    """The file's current version (never older ones), through the token"""
    link = _open(token)
    if link.item.kind != Kind.FILE:
        raise Http404
    return _private(attachments.serve(link.item.upload.versions.all()[0]))


@login_not_required
@require_GET
def public_preview(request, token):
    """The preview of the file's current version, through the token"""
    link = _open(token)
    if link.item.kind != Kind.FILE:
        raise Http404
    response = previews.serve(link.item.upload.versions.all()[0])
    if response is None:
        raise Http404
    return _private(response)
