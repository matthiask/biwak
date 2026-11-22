"""The pages of teams (specs/teams.md, "Managing teams"): a section of the
People page, a page per team, and modals to create, edit and delete them
(``biwak/modals.py``). Staff see teams (externals the members they may
know), own staff manage them; clients get 404."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy

from biwak.accounts.models import User
from biwak.forms import Form, PeopleField, PeopleSelect
from biwak.modals import form_response
from biwak.teams import operations as team_ops
from biwak.teams.models import Team
from biwak.teams.picking import visible_teams


def seeing(request):
    if not team_ops.can_see(request.user):
        raise Http404


def team_for(request, pk, *, manage=False):
    seeing(request)
    team = get_object_or_404(Team, pk=pk)
    if manage and not team_ops.can_manage(request.user):
        raise PermissionDenied
    return team


def teams_url():
    return reverse("people") + "#teams"


def team_detail(request, pk):
    team = team_for(request, pk)
    [(team, members)] = [
        (t, people) for t, people in visible_teams(request.user) if t.pk == team.pk
    ]
    return render(
        request,
        "teams/team_detail.html",
        {
            "team": team,
            "members": members,
            "can_manage": team_ops.can_manage(request.user),
        },
    )


class TeamForm(Form):
    name = forms.CharField(label=gettext_lazy("Name"), max_length=team_ops.NAME_LENGTH)
    members = PeopleField(
        label=gettext_lazy("Members"),
        queryset=User.objects.none(),
        widget=PeopleSelect(attrs={"data-placeholder": gettext_lazy("Add people…")}),
        help_text=gettext_lazy(
            "Anyone, staff, externals and clients. Picking the team picks its"
            " members; changing the team later doesn't change earlier picks."
        ),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None:
            kwargs.setdefault(
                "initial",
                {"name": instance.name, "members": list(instance.members.all())},
            )
        super().__init__(*args, **kwargs)
        # Anyone, active or not (own staff know everybody)
        self.fields["members"].queryset = User.objects.select_related(
            "organization"
        ).order_by("-is_active", Lower("full_name"), "email")

    def clean_name(self):
        return team_ops.clean_name(self.cleaned_data["name"], instance=self.instance)


def team_create(request):
    seeing(request)
    if not team_ops.can_manage(request.user):
        raise PermissionDenied
    form = TeamForm(request.POST or None)
    if form.is_valid():
        try:
            team = team_ops.create_team(actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error("name", exc)
        else:
            return redirect(team)
    return form_response(
        request,
        form,
        title=_("New team"),
        intro=_(
            "Staff find teams among the people when assigning, adding"
            " subscribers and mentioning. Clients never see them."
        ),
        cancel_url=teams_url(),
        submit_label=_("Add team"),
        help_page="orientation",
    )


def team_edit(request, pk):
    team = team_for(request, pk, manage=True)
    form = TeamForm(request.POST or None, instance=team)
    if form.is_valid():
        try:
            team_ops.update_team(team, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error("name", exc)
        else:
            return redirect(team)
    return form_response(
        request,
        form,
        title=_("Edit %(team)s") % {"team": team},
        cancel_url=team.get_absolute_url(),
        submit_label=_("Save"),
    )


def team_delete(request, pk):
    team = team_for(request, pk, manage=True)
    if request.method == "POST":
        team_ops.delete_team(team, actor=request.user)
        messages.success(request, _("%(team)s has been deleted.") % {"team": team})
        return redirect(teams_url())
    return form_response(
        request,
        None,
        title=_("Delete %(team)s?") % {"team": team},
        intro=_(
            "Who was assigned, subscribed or mentioned with it stays so: only"
            " the people were picked."
        ),
        cancel_url=team.get_absolute_url(),
        submit_label=_("Delete"),
        destructive=True,
    )
