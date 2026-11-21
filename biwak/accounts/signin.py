"""The settings page's sign-in section (specs/ui-round-2.md part E): the
passkeys and sessions inline. allauth does the work: its webauthn views add
and remove passkeys, its usersessions flows end sessions."""

import re

from allauth.mfa.models import Authenticator
from allauth.usersessions.internal import flows
from allauth.usersessions.models import UserSession
from allauth.usersessions.views import list_usersessions
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST


BROWSERS = [
    ("Edg", "Edge"),
    ("OPR", "Opera"),
    ("Firefox", "Firefox"),
    ("Chrome", "Chrome"),
    ("Chromium", "Chromium"),
    ("Safari", "Safari"),
]
SYSTEMS = [
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
]


def describe_agent(user_agent):
    """ "Firefox on Linux" from a User-Agent header; the header itself is the
    fallback, it's all there is"""
    browser = next((name for token, name in BROWSERS if token in user_agent), "")
    system = next((name for token, name in SYSTEMS if token in user_agent), "")
    if browser and system:
        return _("%(browser)s on %(system)s") % {"browser": browser, "system": system}
    return browser or system or re.sub(r"\s+", " ", user_agent).strip()


def passkeys(user):
    return Authenticator.objects.filter(
        user=user, type=Authenticator.Type.WEBAUTHN
    ).order_by("created_at")


def sessions(request):
    """The person's live sessions, the current one first"""
    ret = []
    for session in UserSession.objects.purge_and_list(request.user):
        session.current = session.is_current()
        session.browser = describe_agent(session.user_agent)
        ret.append(session)
    return sorted(ret, key=lambda s: (not s.current, -s.last_seen_at.timestamp()))


def context(request):
    return {"passkeys": passkeys(request.user), "sessions": sessions(request)}


def back_to_the_section():
    return redirect(reverse("settings") + "#sign-in")


def passkeys_page(request):
    """The pages allauth lists passkeys on (and returns to after adding or
    removing one) are the settings page's section now"""
    return back_to_the_section()


def sessions_page(request):
    """Likewise for sessions; "Sign out everywhere else" posts to allauth's
    view, which ends them and comes back here"""
    if request.method == "GET":
        return back_to_the_section()
    return list_usersessions(request)


@require_POST
def end_session(request, pk):
    """One other session; this one ends with "Sign out" in the Me menu"""
    session = get_object_or_404(UserSession, pk=pk, user=request.user)
    if session.is_current():
        raise Http404("Not the current session")
    flows.sessions.end_sessions(request, [session])
    messages.info(request, _("That session has been signed out."))
    return back_to_the_section()
