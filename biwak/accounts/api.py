"""Who is using the API, and their API tokens (biwak me, biwak tokens,
biwak logout)"""

import datetime as dt
from typing import Literal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from biwak.accounts.api_auth import user_auth
from biwak.accounts.models import APIToken
from biwak.api_conventions import PersonOut, person_out


router = Router(tags=["accounts"])


class MeOut(PersonOut):
    email: str
    is_admin: bool
    access: Literal["read", "write"]


@router.get("me/", response=MeOut)
def me(request):
    """The authenticated person and the access of their token"""
    token = getattr(request, "api_token", None)
    return person_out(request.user) | {
        "email": request.user.email,
        "is_admin": request.user.is_admin,
        "access": token.access if token else "write",
    }


class APITokenOut(Schema):
    id: int
    title: str
    access: Literal["read", "write"]
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    expires_at: dt.datetime
    current: bool = Field(description="Whether this token authenticated the request.")


def api_token_out(token, request):
    current = getattr(request, "api_token", None)
    return {
        "id": token.pk,
        "title": token.title,
        "access": token.access,
        "created_at": token.created_at,
        "last_used_at": token.last_used_at,
        "expires_at": token.expires_at,
        "current": bool(current and current.pk == token.pk),
    }


@router.get("tokens/", response=list[APITokenOut])
def api_token_list(request):
    """The person's API tokens which haven't expired"""
    return [
        api_token_out(token, request)
        for token in request.user.api_tokens.filter(expires_at__gt=timezone.now())
    ]


@router.delete(
    "tokens/current/", response=APITokenOut, auth=user_auth(allow_read_only=True)
)
def api_token_delete_current(request):
    """Revoke the token which authenticated the request (logging out);
    read-only tokens may do this too"""
    if not (token := getattr(request, "api_token", None)):
        raise HttpError(400, _("This request wasn't authenticated with a token."))
    result = api_token_out(token, request)
    token.delete()
    return result


@router.delete(
    "tokens/{token_id}/", response=APITokenOut, auth=user_auth(allow_read_only=True)
)
def api_token_delete(request, token_id: int):
    """Revoke one of the person's tokens; read-only tokens only themselves"""
    token = get_object_or_404(request.user.api_tokens, pk=token_id)
    current = getattr(request, "api_token", None)
    if current and current.access == APIToken.Access.READ and current.pk != token.pk:
        raise HttpError(403, _("This API token only allows reading, not changes."))
    result = api_token_out(token, request)
    token.delete()
    return result
