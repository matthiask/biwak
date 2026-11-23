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
from biwak.accounts.marks import MARKS
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
    language: Literal["", "de", "en"] = Field(
        description="The language of pages and mails: de, en, or empty for the"
        " browser's (mails: English or the invitation's)."
    )


def me_out(request):
    token = getattr(request, "api_token", None)
    return person_out(request.user) | {
        "email": request.user.email,
        "is_admin": request.user.is_admin,
        "access": token.access if token else "write",
        "keyboard_shortcuts": request.user.keyboard_shortcuts,
        "theme": request.user.theme,
        "accent": request.user.accent,
        "language": request.user.language,
    }


@router.get("me/", response=MeOut)
def me(request):
    """The authenticated person, the access of their token and their
    preferences for the web interface"""
    return me_out(request)


Mark = Literal[tuple(MARKS)]


class MeIn(Schema):
    keyboard_shortcuts: bool | None = None
    theme: Theme | None = None
    accent: Accent | None = None
    language: Literal["", "de", "en"] | None = None
    mark: Mark | None = Field(
        None, description="Your drawn mark, shown while you have no profile image."
    )


@router.put("me/", response=MeOut)
def me_update(request, data: MeIn):
    """Changes the preferences that are given"""
    operations.set_preferences(
        request.user,
        keyboard_shortcuts=data.keyboard_shortcuts,
        theme=data.theme,
        accent=data.accent,
        language=data.language,
        mark=data.mark,
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
    """Removes your profile image: your drawn mark is shown again"""
    operations.remove_image(request.user, actor=request.user)
    return me_out(request)


# Out of office (specs/quiet-hours.md) ---------------------------------------


class AwayIn(Schema):
    until: dt.date = Field(description="The last day away, today or later.")
    note: str = Field(
        "",
        max_length=200,
        description="Optional, one line shown with the name (line breaks"
        " become spaces).",
    )


@router.put("me/away/", response=MeOut)
def me_away(request, data: AwayIn):
    """Sets you away until a day: nothing is mailed meanwhile, the day
    after one digest says what happened; your mark shows it"""
    operations.set_away(
        request.user, until=data.until, note=data.note, actor=request.user
    )
    return me_out(request)


@router.delete("me/away/", response=MeOut)
def me_back(request):
    """Ends being away early ("I'm back")"""
    operations.end_away(request.user, actor=request.user)
    return me_out(request)


def _person(request, person_id):
    from biwak.organizations.people import known_people

    return get_object_or_404(known_people(request.user), pk=person_id)


@router.put("people/{person_id}/away/", response=PersonOut)
def person_away(request, person_id: int, data: AwayIn):
    """Sets somebody away (admins, when someone forgot)"""
    person = _person(request, person_id)
    operations.set_away(person, until=data.until, note=data.note, actor=request.user)
    return person_out(person)


@router.delete("people/{person_id}/away/", response=PersonOut)
def person_back(request, person_id: int):
    """Ends somebody's away time early (admins)"""
    person = _person(request, person_id)
    operations.end_away(person, actor=request.user)
    return person_out(person)


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


class PushSubscriptionOut(Schema):
    id: int
    name: str = Field(
        description="What the person calls the device in the settings, or the"
        " browser and system when they didn't name it."
    )
    device: str = Field(description='The browser and system, "Firefox on Linux".')
    user_agent: str
    created_at: dt.datetime
    last_success_at: dt.datetime | None = Field(
        description="When a push last reached the browser's push service."
    )


def push_subscription_out(subscription):
    from biwak.accounts.signin import describe_agent

    return {
        "id": subscription.pk,
        "name": subscription.label,
        "device": describe_agent(subscription.user_agent),
        "user_agent": subscription.user_agent,
        "created_at": subscription.created_at,
        "last_success_at": subscription.last_success_at,
    }


@router.get("me/push-subscriptions/", response=list[PushSubscriptionOut])
def push_subscription_list(request):
    """The person's devices getting push notifications (specs/web-push.md);
    devices subscribe in the browser, not through the API"""
    return [push_subscription_out(s) for s in request.user.push_subscriptions.all()]


@router.delete("me/push-subscriptions/{subscription_id}/", response=PushSubscriptionOut)
def push_subscription_delete(request, subscription_id: int):
    """Stop pushing to one of the person's devices"""
    subscription = get_object_or_404(
        request.user.push_subscriptions, pk=subscription_id
    )
    result = push_subscription_out(subscription)
    operations.remove_device(request.user, pk=subscription.pk)
    return result


class PushTestOut(Schema):
    sent: bool = Field(description="Whether the device's push service took it.")
    removed: bool = Field(
        description="The push service said the subscription is gone: the"
        " device was removed (turn push notifications on again on it)."
    )
    detail: str = Field(description="What happened, as the settings say it.")


@router.post("me/push-subscriptions/{subscription_id}/test/", response=PushTestOut)
def push_subscription_test(request, subscription_id: int):
    """Send a test push to one of the person's devices at once, whatever
    the quiet hours or being away (specs/web-push.md); 404 without push
    notifications set up on the server"""
    from biwak.activity import push

    subscription = get_object_or_404(
        request.user.push_subscriptions, pk=subscription_id
    )
    if not push.enabled():
        raise HttpError(404, _("Push notifications aren't set up on this server."))
    tested = push.send_test(subscription)
    return {"sent": tested.sent, "removed": tested.removed, "detail": tested.message}
