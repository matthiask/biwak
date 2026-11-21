# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# governance/modals.py, see NOTICE)
"""Forms in a modal (``frontend/modal.js``): links with ``data-modal`` load
their form with the ``HX-Modal`` header into a ``<dialog>``, the form posts
there too. Every modal form is also a page: the views stay as they are and
render ``modal_form.html`` (``form_response()``), which renders only the
form for these requests. Redirects (saving, also the login's) become
``HX-Redirect``, which loads the page like without JavaScript. Requests made
by ``fetch`` follow redirects themselves, so they have to be answered here.
Errors render the form again, in the dialog."""

from django.http import HttpResponse
from django.shortcuts import render


def is_modal(request):
    return request.headers.get("HX-Modal") == "true"


def modal_middleware(get_response):
    def middleware(request):
        response = get_response(request)
        if is_modal(request) and response.status_code in {301, 302, 303}:
            return HttpResponse(headers={"HX-Redirect": response["Location"]})
        return response

    return middleware


def context(request):
    return {"modal": is_modal(request)}


def form_response(
    request,
    form,
    *,
    title,
    cancel_url,
    item=None,
    project=None,
    parent=None,
    intro="",
    submit_label=None,
    destructive=False,
    multipart=False,
    template="modal_form.html",
):
    """The form as a modal or as a page (``modal_form.html``): ``title`` is
    the heading, ``item`` the item it's about (the client banner shows
    where clients see it), ``intro`` says what it does, ``cancel_url`` is
    where Cancel goes on the page. ``form`` can be ``None`` for a question
    (the trash): the buttons only. ``template`` extends ``modal_form.html``
    for more than the form's fields (block ``fields``)."""
    return render(
        request,
        template,
        {
            "form": form,
            "title": title,
            "cancel_url": cancel_url,
            "item": item,
            "project": project or (item.project if item else None),
            "parent": parent,
            "intro": intro,
            "submit_label": submit_label,
            "destructive": destructive,
            "multipart": multipart,
        },
    )
