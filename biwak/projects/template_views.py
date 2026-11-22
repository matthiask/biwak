"""Templates (specs/templates.md): the templates page, a new template and
a list from a template. A new project from a template is the new project
form (``views.project_create``) with ``?template=ID``."""

from django import forms
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import get_text_list
from django.utils.translation import gettext, gettext_lazy as _, ngettext

from biwak.accounts.models import Color
from biwak.forms import ColorSwatches, ComboboxSelect, Form, ModelForm
from biwak.items import across, operations as ops
from biwak.items.models import Item, Kind, Status
from biwak.modals import form_response
from biwak.projects import operations as project_ops
from biwak.projects.models import Project


def templates_for(user):
    """The templates the person sees: all of them for the own staff,
    none for anybody else"""
    if not project_ops.can_use_templates(user):
        return Project.objects.none()
    return Project.objects.accessible_to(user).templates()


def _check(request):
    """Clients and externals never see templates: 404, like a project they
    can't open"""
    if not project_ops.can_use_templates(request.user):
        raise Http404


# What the cards count, in this order
COUNTED = [
    (
        "lists",
        Q(kind=Kind.LIST, parent=None, status=Status.ACTIVE),
        lambda n: ngettext("%(count)d list", "%(count)d lists", n),
    ),
    (
        "todos",
        Q(
            kind=Kind.TODO,
            parent__status=Status.ACTIVE,
            todo__completed_at__isnull=True,
            status=Status.ACTIVE,
        ),
        lambda n: ngettext("%(count)d to-do", "%(count)d to-dos", n),
    ),
    (
        "checkins",
        Q(kind=Kind.QUESTION, status=Status.ACTIVE),
        lambda n: ngettext("%(count)d check-in", "%(count)d check-ins", n),
    ),
    (
        "messages",
        Q(kind=Kind.MESSAGE, status=Status.ACTIVE),
        lambda n: ngettext("%(count)d message", "%(count)d messages", n),
    ),
    (
        "folders",
        Q(kind=Kind.FOLDER, status=Status.ACTIVE),
        lambda n: ngettext("%(count)d folder", "%(count)d folders", n),
    ),
    (
        "docs",
        Q(kind=Kind.DOC, status=Status.ACTIVE, is_draft=False),
        lambda n: ngettext("%(count)d doc", "%(count)d docs", n),
    ),
    (
        "files",
        Q(kind=Kind.FILE, status=Status.ACTIVE),
        lambda n: ngettext("%(count)d file", "%(count)d files", n),
    ),
]


def holds(templates):
    """``template.holds``: what each template holds ("3 lists · 160 to-dos
    · 4 messages · 7 folders"), what it has none of left out; one query"""
    templates = list(templates)
    counts = {
        row["project"]: row
        for row in Item.objects
        .filter(project__in=templates)
        .values("project")
        .annotate(**{
            name: Count("pk", filter=condition) for name, condition, _label in COUNTED
        })
    }
    for template in templates:
        row = counts.get(template.pk, {})
        template.holds = " · ".join(
            label(row[name]) % {"count": row[name]}
            for name, _condition, label in COUNTED
            if row.get(name)
        )
    return templates


def template_list(request):
    """``/projects/templates/``: cards like the projects', ``?archived=1``
    the archived templates"""
    _check(request)
    archived = bool(request.GET.get("archived"))
    templates = templates_for(request.user).filter(archived_at__isnull=not archived)
    return render(
        request,
        "projects/templates.html",
        {
            "templates": holds(templates.order_by(Lower("name"), "pk")),
            "archived": archived,
        },
    )


class TemplateForm(ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "color"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "data-toolbar": ""}),
            "color": ColorSwatches,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["color"].choices = [("", _("None")), *Color.choices]
        self.fields["description"].help_text = _(
            "Projects made from it get its description, to change."
        )


def template_create(request):
    """ "New template": a modal, also a page"""
    _check(request)
    form = TemplateForm(request.POST or None)
    if form.is_valid():
        template = project_ops.create_template(actor=request.user, **form.cleaned_data)
        return redirect(template)
    return form_response(
        request,
        form,
        title=_("New template"),
        cancel_url=reverse("templates"),
        submit_label=_("Add template"),
    )


def client_visible_titles(template):
    """The titles of what clients will see of a project made from the
    template: its top-level items visible to clients that are copied"""
    return list(
        ops
        .template_contents(template)
        .filter(is_client_visible=True)
        .values_list("title", flat=True)
    )


def clients_note(template):
    """ "Visible to clients: Welcome, Questions for you", or nothing"""
    titles = client_visible_titles(template)
    if not titles:
        return ""
    return _("Visible to clients: %(titles)s") % {
        "titles": get_text_list(titles, gettext("and"))
    }


# A list from a template ------------------------------------------------------


def list_label(item):
    """ "Onboarding [name] · Lists library" """
    return f"{item.title} · {item.project.name}"


class TemplateListChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return list_label(obj)


class PickForm(Form):
    """The first step: which list"""

    step = forms.CharField(widget=forms.HiddenInput, initial="pick", required=False)
    source = TemplateListChoice(
        Item.objects.none(), label=_("List"), widget=ComboboxSelect()
    )

    def __init__(self, *args, lists, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source"].queryset = lists


class FromTemplateForm(across.CopyForm):
    """The second step, the copy modal of lists-across-projects.md the
    other way round: the list from a template into this project"""

    step = forms.CharField(widget=forms.HiddenInput, initial="copy", required=False)

    def __init__(self, *args, lists, project, **kwargs):
        super().__init__(
            *args, projects=Project.objects.filter(pk=project.pk), **kwargs
        )
        del self.fields["project"]
        self.project = project
        self.fields["source"] = TemplateListChoice(
            lists, label=_("List"), widget=forms.HiddenInput
        )
        self.fields["title"].help_text = _(
            "Fill in what the template leaves open, like a name."
        )
        if project.is_template:
            # Nobody sees anything in a template
            del self.fields["visible"]


def template_lists(user):
    """The active lists in templates the person sees, by template and
    position"""
    return (
        Item.objects
        .visible_to(user)
        .filter(
            kind=Kind.LIST,
            parent=None,
            status=Status.ACTIVE,
            project__in=templates_for(user).filter(archived_at__isnull=True),
        )
        .select_related("project")
        .order_by(Lower("project__name"), "project_id", "position", "pk")
    )


def offers_template_lists(user, project):
    """Whether "New list" offers "From a template…": for the own staff,
    in projects not archived, when there are lists in templates"""
    return (
        project.archived_at is None
        and ops.can_create(user, Kind.LIST)
        and template_lists(user).exists()
    )


def list_from_template(request, pk):
    """ "From a template…" of "New list": the combobox of the lists in
    templates, then the copy modal (title, dates, visibility) filled in
    from the list chosen; copied with ``copy_list()``"""
    from biwak.projects.views import project_for

    project = project_for(request, pk)
    _check(request)
    if project.archived_at is not None or not ops.can_create(request.user, Kind.LIST):
        raise Http404
    lists = template_lists(request.user)
    data = request.POST or None
    notes = across.NO_NOTES
    if data is not None and data.get("step") == "copy":
        form = FromTemplateForm(data, lists=lists, project=project)
        if form.is_valid():
            response, notes = _copy(request, form, project)
            if response is not None:
                return response
    else:
        form = PickForm(data, lists=lists)
        if form.is_valid():
            source = form.cleaned_data["source"]
            form = FromTemplateForm(
                lists=lists,
                project=project,
                initial={"source": source, "title": source.title},
            )
    copying = isinstance(form, FromTemplateForm)
    chosen = _chosen(form, lists) if copying else ""
    note, clients = notes
    return form_response(
        request,
        form,
        title=_("New list from a template"),
        project=project,
        cancel_url=project.get_absolute_url(),
        intro=_("From %(list)s.") % {"list": chosen} if chosen else "",
        submit_label=_("Add list") if copying else _("Continue"),
        destructive=bool(clients),
        template="items/across_form.html",
        extra={"note": note, "clients_note": clients},
    )


def _chosen(form, lists):
    """The label of the list chosen in the first step"""
    value = form["source"].value()
    if not isinstance(value, Item):
        value = lists.filter(pk=value).first() if str(value).isdigit() else None
    return list_label(value) if value is not None else ""


def _copy(request, form, project):
    """Copies once the person saw what it does (``form.asked()``):
    ``(response or None, notes)``"""
    data = form.cleaned_data
    item, visible = data["source"], data.get("visible", False)
    notes = across.copy_notes(item, project, visible, request.user)
    if any(notes) and not form.asked(f"{item.pk}:{int(visible)}"):
        return None, notes
    try:
        copy = ops.copy_list(
            item,
            project=project,
            title=data["title"],
            actor=request.user,
            dates=data["dates"],
            days=data["days"] or 0,
            visible=visible,
        )
    except ValueError as exc:
        form.add_error(None, str(exc))
        return None, across.NO_NOTES
    return redirect(copy), across.NO_NOTES
