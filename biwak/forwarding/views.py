"""The "Forwarded" page (specs/forwarding.md): the person's forwarded
mails, filing them as a message or a to-do, deleting them. Nobody but the
forwarder sees a forwarded mail: everything else gets 404."""

import re

from django import forms
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from biwak.files import attachments, file_urls
from biwak.forms import BLANK_CHOICE_LABEL, ComboboxSelect, Form
from biwak.forwarding import operations as ops
from biwak.forwarding.models import REFERENCE, ForwardedFile
from biwak.items.models import Group, Kind, MessageCategory
from biwak.items.views import item_for
from biwak.modals import form_response
from biwak.projects.models import Project
from biwak.projects.views import project_for
from biwak.templatetags.biwak import render_markdown


def _forwarded(request):
    """The person's forwarded mails; 404 while forwarding is off and for
    clients"""
    if not ops.enabled() or not ops.can_forward(request.user):
        raise Http404
    return ops.forwarded_for(request.user)


def forwarded_for(request, pk):
    """One of the person's forwarded mails, else 404"""
    return get_object_or_404(_forwarded(request), pk=pk)


def text_html(mail, *, absolute=False):
    """The text with its files: on the page (only the forwarder's) at the
    storage's URLs (``file_urls``), in the API (``absolute``) through the
    forwarder's downloads"""
    files = {file.key: file for file in mail.files.all()}
    urls = {
        key: settings.BASE_URL + file.get_absolute_url()
        if absolute
        else file_urls.file_url(file)
        for key, file in files.items()
    }

    def url(match):
        return f"(<{urls[match[1]]}>)" if match[1] in urls else "()"

    html = str(render_markdown(REFERENCE.sub(url, mail.text), attachment_urls=False))
    # Scaled to the text's width like attachments
    own = {escape(u) for u in urls.values()}
    html = re.sub(
        r'<img src="([^"]*)"',
        lambda m: (
            f'<img class="wb-attachment-image" loading="lazy" src="{m[1]}"'
            if m[1] in own
            else m[0]
        ),
        html,
    )
    return mark_safe(html)


@never_cache
def forwarded(request):
    mails = _forwarded(request).prefetch_related("files")
    return render(
        request,
        "forwarding/list.html",
        {
            "mails": [(mail, text_html(mail)) for mail in mails],
            "address": ops.address(),
            "keep_days": ops.KEEP_DAYS,
        },
    )


@require_GET
def download(request, pk, key, name):
    """A file of one of the person's forwarded mails"""
    file = get_object_or_404(
        ForwardedFile, mail__in=_forwarded(request), mail=pk, key=key
    )
    return attachments.serve(file)


# Filing -----------------------------------------------------------------------


class FileMessageForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    project = forms.ModelChoiceField(
        label=_("project"),
        queryset=Project.objects.none(),
        widget=ComboboxSelect,
        empty_label=BLANK_CHOICE_LABEL,
    )
    category = forms.ModelChoiceField(
        label=_("Category"),
        queryset=MessageCategory.objects.all(),
        required=False,
        empty_label=_("None"),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = ops.message_projects(user)


class TargetSelect(ComboboxSelect):
    """Options of lists clients see carry ``data-client``: choosing one
    shows the note saying so (``frontend/clients-note.js``)"""

    def __init__(self, attrs=None):
        super().__init__({"data-clients-note": "#clients-note", **(attrs or {})})
        self.visible = set()

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if str(value) in self.visible:
            option["attrs"]["data-client"] = "true"
        return option


class FileTodoForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    target = forms.ChoiceField(label=_("List and group"), widget=TargetSelect)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        choices = {}
        visible = set()
        for todolist in ops.todo_lists(user):
            options = [
                (str(todolist.pk), str(todolist)),
                *(
                    (f"{todolist.pk}:{group.pk}", f"{todolist} / {group}")
                    for group in todolist.todolist.groups.all()
                ),
            ]
            if todolist.is_client_visible:
                # Like "Move to…"
                suffix = _("clients can see this")
                options = [(value, f"{label} ({suffix})") for value, label in options]
                visible.update(value for value, _label in options)
            choices.setdefault(str(todolist.project), []).extend(options)
        self.fields["target"].choices = [("", BLANK_CHOICE_LABEL), *choices.items()]
        self.fields["target"].widget.visible = visible

    def clients_see(self):
        """Whether the list chosen (when the form is shown again) is one
        clients see"""
        return str(self["target"].value()) in self.fields["target"].widget.visible


def file_message(request, pk):
    """File as message…: an internal message in a project"""
    mail = forwarded_for(request, pk)
    form = FileMessageForm(
        request.POST or None, user=request.user, initial={"title": mail.subject}
    )
    if form.is_valid():
        data = form.cleaned_data
        item = ops.file_as_message(
            mail,
            project=project_for(request, data["project"].pk),
            title=data["title"],
            category=data["category"],
            actor=request.user,
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("File as message"),
        intro=_("An internal message by you, with the mail's text and files."),
        cancel_url=reverse("forwarded"),
        help_page="notifications",
        submit_label=_("Post message"),
    )


def file_todo(request, pk):
    """File as to-do…: a to-do in a list, optionally a group; visible to
    clients when the list is, which the note under the choice says"""
    mail = forwarded_for(request, pk)
    form = FileTodoForm(
        request.POST or None, user=request.user, initial={"title": mail.subject}
    )
    if form.is_valid():
        data = form.cleaned_data
        list_id, _sep, group_id = data["target"].partition(":")
        todolist = item_for(request, int(list_id), Kind.LIST)
        group = None
        if group_id:
            group = get_object_or_404(
                Group, pk=int(group_id), todolist=todolist.todolist
            )
        item = ops.file_as_todo(
            mail,
            todolist=todolist,
            group=group,
            title=data["title"],
            actor=request.user,
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("File as to-do"),
        intro=_("A to-do by you, with the mail's text as its notes and its files."),
        cancel_url=reverse("forwarded"),
        help_page="notifications",
        submit_label=_("Add to-do"),
        template="forwarding/file_todo.html",
    )


def delete(request, pk):
    """Delete: asks first, it can't be restored"""
    mail = forwarded_for(request, pk)
    if request.method == "POST":
        ops.delete(mail, actor=request.user)
        return redirect("forwarded")
    return form_response(
        request,
        None,
        title=_("Delete the forwarded mail?"),
        intro=_("“%(subject)s” is deleted with its files. It can't be restored.")
        % {"subject": mail.subject or mail.sender},
        cancel_url=reverse("forwarded"),
        submit_label=_("Delete"),
        destructive=True,
    )
