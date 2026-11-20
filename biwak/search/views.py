"""The search page (specs/search.md)"""

from django import forms
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from biwak import cursors
from biwak.forms import Form
from biwak.items.models import Kind
from biwak.projects.models import Project
from biwak.search import queries


KIND_ICONS = {
    Kind.LIST: "list-check",
    Kind.TODO: "check-circle",
    Kind.MESSAGE: "chat-left-text",
    Kind.FOLDER: "folder",
    Kind.DOC: "file-earmark-text",
    Kind.QUESTION: "chat-square-text",
    Kind.ANSWER: "card-text",
    Kind.FILE: "file-earmark",
}


class SearchForm(Form):
    q = forms.CharField(label=_("Search"), max_length=200, required=False)
    project = forms.ModelChoiceField(
        label=_("Project"),
        queryset=Project.objects.none(),
        required=False,
        empty_label=_("All projects"),
    )
    kind = forms.ChoiceField(
        label=_("Kind"), choices=[("", _("All")), *Kind.choices], required=False
    )
    mine = forms.BooleanField(label=_("Only mine"), required=False)
    exclude_archived = forms.BooleanField(
        label=_("Without archived projects"), required=False
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.accessible_to(user)


def search(request):
    form = SearchForm(request.GET or None, user=request.user)
    data = form.cleaned_data if form.is_valid() else {}
    terms = data.get("q", "").strip()
    results, older = [], None
    if terms:
        found = queries.search(
            request.user,
            terms,
            project=data["project"],
            kind=data["kind"],
            mine=data["mine"],
            exclude_archived=data["exclude_archived"],
        )
        if before := request.GET.get("before"):
            try:
                updated_at, pk = cursors.decode(before)
            except ValueError:
                return HttpResponseBadRequest("Invalid cursor.")
            found = found.filter(
                Q(updated_at__lt=updated_at) | Q(updated_at=updated_at, pk__lt=pk)
            )
        page = list(found[: queries.PAGE_SIZE + 1])
        more = len(page) > queries.PAGE_SIZE
        page = page[: queries.PAGE_SIZE]
        hits = queries.hits(page, terms)
        results = [
            {"item": item, "hit": hits[item.pk], "icon": KIND_ICONS[item.kind]}
            for item in page
        ]
        if more:
            query = request.GET.copy()
            query["before"] = cursors.encode(page[-1].updated_at, page[-1].pk)
            older = f"{reverse('search')}?{query.urlencode()}"
    return render(
        request,
        "search/search.html",
        {
            "form": form,
            "terms": terms,
            "results": results,
            "older": older,
            "filtered": any(
                request.GET.get(name)
                for name in ["project", "kind", "mine", "exclude_archived"]
            ),
        },
    )
