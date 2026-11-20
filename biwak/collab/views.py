from django.shortcuts import render

from biwak.items import operations as ops
from biwak.items.models import Kind
from biwak.items.views import item_for


def spike(request, pk):
    item = item_for(request, pk, Kind.DOC)
    return render(
        request,
        "collab/spike.html",
        {
            "item": item,
            "readonly": not ops.can_change(request.user, item),
            "hocuspocus": request.GET.get("hp"),
        },
    )


# SPIKE: Hocuspocus asks Django -------------------------------------------
import json  # noqa: E402

from django.contrib.auth.decorators import login_not_required  # noqa: E402
from django.http import Http404, JsonResponse  # noqa: E402
from django.views.decorators.csrf import csrf_exempt  # noqa: E402

from biwak.accounts.models import User  # noqa: E402
from biwak.files import operations as file_ops  # noqa: E402
from biwak.items.models import Item  # noqa: E402


def hp_auth(request, pk):
    item = item_for(request, pk, Kind.DOC)
    return JsonResponse({
        "writable": ops.can_change(request.user, item),
        "user": request.user.pk,
    })


@login_not_required
@csrf_exempt
def hp_content(request, pk):
    if request.headers.get("x-service-token") != "spike":
        raise Http404
    item = Item.objects.get(pk=pk, kind=Kind.DOC)
    if request.method == "POST":
        data = json.loads(request.body)
        file_ops.update_doc(
            item, actor=User.objects.get(pk=data["user"]), content=data["content"]
        )
    return JsonResponse({"content": item.doc.content})
