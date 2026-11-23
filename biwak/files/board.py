"""The message board (specs/files.md, stage 2)"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak import cursors
from biwak.activity import timeline as timelines
from biwak.files import operations
from biwak.files.common import NotifyForm, comments_context, sidebar_context
from biwak.files.queries import (
    board,
    latest_messages,
    messages_order,
    pinned_messages,
)
from biwak.forms import Form, next_url
from biwak.items import editing, operations as ops
from biwak.items.models import Kind, MessageCategory
from biwak.items.views import item_for
from biwak.projects.models import MessagesOrder
from biwak.projects.views import project_for


# Messages per page of the board besides the pinned ones (not decided in
# the spec; the board grows)
PAGE_SIZE = 50


def project_messages(request, pk):
    project = project_for(request, pk)
    messages = board(project, request.user)
    order = messages_order(project, request.GET.get("order"))
    latest = latest_messages(messages, order)
    before = request.GET.get("before")
    pinned = []
    if before:
        try:
            at, last = cursors.decode(before)
        except ValueError:
            return HttpResponseBadRequest("Invalid cursor.")
        latest = latest.filter(Q(sort_at__lt=at) | Q(sort_at=at, pk__lt=last))
    else:
        pinned = list(pinned_messages(messages))
    rows = list(latest[: PAGE_SIZE + 1])
    cursor = None
    if len(rows) > PAGE_SIZE:
        rows = rows[:PAGE_SIZE]
        cursor = cursors.encode(rows[-1].sort_at, rows[-1].pk)
    return render(
        request,
        "files/board.html",
        {
            "project": project,
            "pinned": pinned,
            "rows": rows,
            "cursor": cursor,
            "order": order,
            # ``?order=`` looks the other way without changing the setting
            "order_given": order != project.messages_order,
            "orders": MessagesOrder.choices,
            "can_order": not request.user.is_client,
            "can_pin": not request.user.is_client,
        },
    )


@require_POST
def project_messages_order(request, pk):
    """The board's order, for everybody; staff only"""
    project = project_for(request, pk)
    if request.user.is_client:
        raise PermissionDenied
    if request.POST.get("order") not in MessagesOrder.values:
        return HttpResponseBadRequest("Invalid order.")
    operations.set_messages_order(project, request.POST["order"], actor=request.user)
    return redirect("project_messages", project.pk)


class MessageEditForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    content = forms.CharField(
        label=_("message"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 10}),
        help_text=_("Markdown"),
    )
    category = forms.ModelChoiceField(
        label=_("Category"),
        queryset=MessageCategory.objects.all(),
        required=False,
        empty_label=_("None"),
    )


class MessageForm(NotifyForm, MessageEditForm):
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)
    field_order = ["title", "content", "category", "visible", "notify", "people"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        if user.is_client:
            # What clients create is visible to clients (specs/access.md)
            self.fields.pop("visible", None)


def message_new(request, pk):
    project = project_for(request, pk)
    form = MessageForm(request.POST or None, project=project, user=request.user)
    form.mention_fields(project, "title", "content")
    if form.is_valid():
        data = form.cleaned_data
        item = ops.create_message(
            project=project,
            title=data["title"],
            content=data["content"],
            category=data["category"],
            creator=request.user,
            visible=data.get("visible", False),
            also=form.also_people(),
        )
        return redirect(item)
    return render(
        request,
        "files/message_form.html",
        {"project": project, "form": form, "item": None},
    )


def message(request, pk):
    item = item_for(request, pk, Kind.MESSAGE)
    comment_form, done = comments_context(request, item)
    if done:
        return done
    return render(
        request,
        "files/message.html",
        {
            "item": item,
            "message": item.message,
            "comment_form": comment_form,
            # Comments and what happened between them (specs/timeline.md)
            "timeline": timelines.entries_for(
                item, request.user, item.comments.select_related("author")
            ),
            "can_pin": not request.user.is_client,
        }
        | sidebar_context(request, item),
    )


def message_edit(request, pk):
    item = item_for(request, pk, Kind.MESSAGE)
    if not ops.can_change(request.user, item):
        raise PermissionDenied
    form = MessageEditForm(
        request.POST or None,
        initial={
            "title": item.title,
            "content": item.message.content,
            "category": item.message.category,
        },
    )
    form.fields["content"].widget.attrs["data-mentions"] = _mentions_url(item)
    form.fields["title"].widget.attrs["data-mentions"] = _mentions_url(item)
    base = request.POST.get("base") or editing.version(item)
    if form.is_valid():
        try:
            operations.update_message(
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
        "files/message_form.html",
        {"project": item.project, "form": form, "item": item, "base": base},
    )


def _mentions_url(item):
    return reverse("mentionable", args=[item.pk])


@require_POST
def message_pin(request, pk):
    """Pins or (``unpin``) unpins; staff only, like the visibility switch"""
    item = item_for(request, pk, Kind.MESSAGE)
    if request.user.is_client:
        raise PermissionDenied
    if request.POST.get("unpin"):
        operations.unpin_message(item, actor=request.user)
    else:
        operations.pin_message(item, actor=request.user)
    return redirect(next_url(request) or item)
