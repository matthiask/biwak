"""Adding to-dos from text: the modal and its preview
(specs/todos-from-text.md)

"Add from text…" of a list, also opened by dropping text files onto a
list (``frontend/from-text.js``, which reads them in the browser and puts
their text into the field). Without JavaScript the file input posts the
file. The preview is rendered here, for the form and for the script.
"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.translation import gettext, gettext_lazy as _

from biwak.forms import ComboboxSelect, Form
from biwak.items import from_text, operations as ops
from biwak.items.models import Item, Kind, Status
from biwak.items.views import item_for
from biwak.modals import form_response


TEXT_EXTENSIONS = (".md", ".markdown", ".txt")


def is_text_file(name, content_type):
    """The files read as text (``.md``, ``.markdown``, ``.txt`` or any
    ``text/*``), the same rule as ``frontend/from-text.js``'s"""
    return (name or "").lower().endswith(TEXT_EXTENSIONS) or (
        content_type or ""
    ).startswith("text/")


def addable_lists(user, project):
    """The lists of the project the person may add to-dos to, in the
    project's order"""
    if project.archived_at is not None or not ops.can_create(user, Kind.TODO):
        return Item.objects.none()
    return (
        Item.objects
        .visible_to(user)
        .filter(project=project, kind=Kind.LIST, status=Status.ACTIVE)
        .select_related("project", "todolist")
        .order_by("position", "pk")
    )


class ListChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return str(obj)


class FromTextForm(Form):
    todolist = ListChoice(
        Item.objects.none(), label=_("list"), widget=ComboboxSelect(), empty_label=None
    )
    text = forms.CharField(
        label=_("text"),
        required=False,
        strip=False,
        # Source, not the editor (specs/todos-from-text.md)
        widget=forms.Textarea(
            attrs={
                "rows": 10,
                "data-toolbar": False,
                "data-mentions": False,
                "data-from-text-field": "",
                "spellcheck": "false",
            }
        ),
        help_text=_(
            "Headings become groups, list items to-dos, what’s indented under "
            "them their notes."
        ),
    )
    file = forms.FileField(
        label=_("Or a file"),
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".md,.markdown,.txt,text/*",
                "multiple": False,
                "data-from-text-file": "",
            }
        ),
    )

    def __init__(self, *args, lists, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["todolist"].queryset = lists
        self.user = user
        self.plan = None

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if not upload:
            return ""
        if not is_text_file(upload.name, upload.content_type):
            raise forms.ValidationError(_("Only text files can be added as to-dos."))
        if upload.size > from_text.MAX_BYTES:
            raise forms.ValidationError(
                _("This file is larger than 200 KB; up to 200 KB can be added at once.")
            )
        try:
            return upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise forms.ValidationError(
                _("This file can’t be read as text (UTF-8).")
            ) from None

    def clean(self):
        data = super().clean()
        text = "\n\n".join(filter(None, [data.get("text", ""), data.get("file", "")]))
        data["text"] = text
        todolist = data.get("todolist")
        if todolist is not None and "file" not in self.errors:
            self.plan = ops.text_plan(todolist, text, self.user)
            if self.plan.problem:
                self.add_error("text", self.plan.problem)
        return data


def _list_and_form(request, pk):
    item = item_for(request, pk, Kind.LIST)
    if not ops.may_add_to(request.user, item):
        raise PermissionDenied(gettext("No to-dos can be added to this list."))
    form = FromTextForm(
        request.POST or None,
        request.FILES or None,
        lists=addable_lists(request.user, item.project),
        user=request.user,
        initial={"todolist": item},
    )
    return item, form


def _preview(form, item, user):
    """The plan shown: of the form's text and list, else of nothing for
    the list the form was opened for"""
    if form.is_bound:
        form.is_valid()
        if form.plan is not None:
            return form.plan
    return ops.text_plan(item, "", user)


def list_from_text(request, pk):
    """ "Add from text…" (a modal, also a page)"""
    item, form = _list_and_form(request, pk)
    if form.is_valid():
        target = form.cleaned_data["todolist"]
        try:
            ops.add_from_text(target, form.cleaned_data["text"], actor=request.user)
        except ops.FromTextRefused as exc:
            form.add_error("text", str(exc))
        else:
            return redirect(target)
    plan = _preview(form, item, request.user)
    return form_response(
        request,
        form,
        title=_("Add from text…"),
        item=item,
        cancel_url=item.get_absolute_url(),
        submit_label=plan.submit_label,
        multipart=True,
        help_page="todos",
        template="items/from_text_form.html",
        extra={"plan": plan, "max_bytes": from_text.MAX_BYTES},
    )


def list_from_text_preview(request, pk):
    """The preview of the posted text and list (``frontend/from-text.js``)"""
    item, form = _list_and_form(request, pk)
    if request.method != "POST":
        form = FromTextForm(lists=form.fields["todolist"].queryset, user=request.user)
    return render(
        request,
        "items/_from_text_preview.html",
        {"plan": _preview(form, item, request.user)},
    )
