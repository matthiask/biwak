from django import forms
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.forms import Form, ModelForm
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.projects.models import Membership, Project


def project_for(request, pk):
    """The project if the person may open it, else 404 (limited projects
    don't reveal that they exist)"""
    return get_object_or_404(Project.objects.accessible_to(request.user), pk=pk)


def project_list(request):
    projects = Project.objects.accessible_to(request.user).active()
    others = Project.objects.none()
    if request.user.is_admin:
        # Admins see that limited projects exist and can join them
        others = Project.objects.active().exclude(pk__in=projects)
    return render(
        request,
        "projects/project_list.html",
        {"projects": projects, "others": others},
    )


class ProjectForm(ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_all_access"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


def project_create(request):
    if request.user.is_client:
        raise PermissionDenied
    form = ProjectForm(request.POST or None)
    if form.is_valid():
        project = form.save()
        Membership.objects.create(project=project, user=request.user)
        return redirect(project)
    return render(
        request,
        "generic/form.html",
        {"form": form, "title": _("New project"), "cancel": "/"},
    )


def project_join(request, pk):
    """Staff join all-access projects, admins also limited ones (recorded:
    specs/access.md); joining subscribes to nothing that exists already"""
    if request.method != "POST" or request.user.is_client:
        raise PermissionDenied
    if request.user.is_admin:
        project = get_object_or_404(Project, pk=pk)
    else:
        project = project_for(request, pk)
    _membership, created = Membership.objects.get_or_create(
        project=project, user=request.user
    )
    if created:
        record(actor=request.user, action=Action.JOINED, project=project)
    return redirect(project)


class ListForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)


def project_detail(request, pk):
    project = project_for(request, pk)
    items = Item.objects.visible_to(request.user).filter(project=project)
    lists = items.filter(kind=Kind.LIST, parent=None).exclude(status="archived")
    form = ListForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = ops.create_list(
            project=project,
            title=form.cleaned_data["title"],
            creator=request.user,
            # What clients create is visible to clients (specs/access.md)
            visible=form.cleaned_data["visible"] or request.user.is_client,
        )
        return redirect(item)
    return render(
        request,
        "projects/project_detail.html",
        {
            "project": project,
            "lists": lists,
            "form": form,
            "members": project.memberships.select_related("user"),
            "is_member": project.is_member(request.user),
            "events": Event.objects
            .visible_to(request.user)
            .filter(project=project)
            .select_related("actor", "item")[:20],
        },
    )
