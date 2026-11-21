"""Who is using the API, and their API tokens (biwak me, biwak tokens,
biwak logout)"""

import datetime as dt
from typing import Literal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from ninja import Field, File, Router, Schema, UploadedFile
from ninja.errors import HttpError

from biwak.accounts import operations
from biwak.accounts.api_auth import user_auth
from biwak.accounts.models import Accent, APIToken, Theme
from biwak.api_conventions import PersonOut, person_out


router = Router(tags=["accounts"])


class MeOut(PersonOut):
    email: str
    is_admin: bool
    access: Literal["read", "write"]
    keyboard_shortcuts: bool = Field(
        description="Single-key shortcuts in the web interface (Ctrl+K always works)."
    )
    theme: Theme
    accent: Accent


def me_out(request):
    token = getattr(request, "api_token", None)
    return person_out(request.user) | {
        "email": request.user.email,
        "is_admin": request.user.is_admin,
        "access": token.access if token else "write",
        "keyboard_shortcuts": request.user.keyboard_shortcuts,
        "theme": request.user.theme,
        "accent": request.user.accent,
    }


@router.get("me/", response=MeOut)
def me(request):
    """The authenticated person, the access of their token and their
    preferences for the web interface"""
    return me_out(request)


class MeIn(Schema):
    keyboard_shortcuts: bool | None = None
    theme: Theme | None = None
    accent: Accent | None = None


@router.put("me/", response=MeOut)
def me_update(request, data: MeIn):
    """Changes the preferences that are given"""
    operations.set_preferences(
        request.user,
        keyboard_shortcuts=data.keyboard_shortcuts,
        theme=data.theme,
        accent=data.accent,
    )
    return me_out(request)


@router.put("me/image/", response=MeOut)
def me_image(request, image: File[UploadedFile]):
    """Sets your profile image (multipart, field ``image``: JPEG, PNG or
    WebP, at most 5 MB); it's cut to a square and scaled to 256 pixels"""
    try:
        operations.set_image(
            request.user,
            image.read(operations.IMAGE_MAX_BYTES + 1),
            actor=request.user,
        )
    except operations.InvalidImage as exc:
        raise HttpError(400, str(exc)) from exc
    return me_out(request)


@router.delete("me/image/", response=MeOut)
def me_image_remove(request):
    """Removes your profile image: the initials are shown again"""
    operations.remove_image(request.user, actor=request.user)
    return me_out(request)


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
