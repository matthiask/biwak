"""The "Forwarded" page (specs/forwarding.md): the person's forwarded
mails, filing them as a message or a to-do, deleting them. Nobody but the
forwarder sees a forwarded mail: everything else gets 404."""

import re

from django import forms
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from biwak.files import attachments
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
    """The text with its files through the forwarder's downloads"""
    files = {file.key: file for file in mail.files.all()}
    prefix = settings.BASE_URL if absolute else ""

    def url(match):
        file = files.get(match[1])
        return f"({prefix}{file.get_absolute_url()})" if file else "()"

    html = str(render_markdown(REFERENCE.sub(url, mail.text), attachment_urls=False))
    # Scaled to the text's width like attachments
    html = re.sub(
        r'<img src="([^"]*/forwarded/\d+/files/[^"]*)"',
        r'<img class="wb-attachment-image" loading="lazy" src="\1"',
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


class FileTodoForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    target = forms.ChoiceField(label=_("List and group"), widget=ComboboxSelect)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        choices = {}
        for todolist in ops.todo_lists(user):
            choices.setdefault(str(todolist.project), []).extend([
                (str(todolist.pk), str(todolist)),
                *(
                    (f"{todolist.pk}:{group.pk}", f"{todolist} / {group}")
                    for group in todolist.todolist.groups.all()
                ),
            ])
        self.fields["target"].choices = [("", BLANK_CHOICE_LABEL), *choices.items()]


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
    """File as to-do…: a to-do in an internal list, optionally a group"""
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
        try:
            item = ops.file_as_todo(
                mail,
                todolist=todolist,
                group=group,
                title=data["title"],
                actor=request.user,
            )
        except ValueError:
            # The list was made visible to clients meanwhile
            form.add_error("target", _("Choose an internal list."))
        else:
            return redirect(item)
    return form_response(
        request,
        form,
        title=_("File as to-do"),
        intro=_(
            "A to-do in an internal list, with the mail's text as its notes"
            " and its files."
        ),
        cancel_url=reverse("forwarded"),
        help_page="notifications",
        submit_label=_("Add to-do"),
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
