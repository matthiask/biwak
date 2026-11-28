"""The webhook providers post to when a reply arrives
(specs/notifications.md, stage 2)"""

import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import Http404, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from biwak.accounts.middleware import set_user_name
from biwak.inbound import providers, tokens
from biwak.inbound.models import InboundMessage
from biwak.inbound.receive import receive
from biwak.outbox import events


logger = logging.getLogger(__name__)


@csrf_exempt
@login_not_required
@require_POST
@transaction.non_atomic_requests
def resend(request):
    """Resend's ``email.received``: signed (Svix), metadata only; the mail
    is fetched through its API. Answers 2xx once handled (also for mails
    dropped or rejected), 5xx when Resend should try again. Also the
    delivery events of the mails we sent (``email.delivered``,
    ``email.bounced``, ``email.complained``; specs/mail-sending.md), with
    the same secret, also while replying is off."""
    if not settings.RESEND_WEBHOOK_SECRET:
        raise Http404
    body = request.body
    if not providers.verify_svix(settings.RESEND_WEBHOOK_SECRET, request.headers, body):
        return HttpResponse("Invalid signature", status=401)
    try:
        event = json.loads(body)
    except ValueError:
        event = None
    if not isinstance(event, dict):
        return HttpResponse("Invalid payload", status=400)
    # What the webhook changes is Resend's, until a mail's sender is known
    # (``receive()`` runs as them; specs/auditing.md)
    set_user_name("Resend")
    if event.get("type") in events.EVENTS:
        events.record(event)
        return HttpResponse(status=204)
    if event.get("type") != "email.received":
        return HttpResponse(status=204)
    if not tokens.enabled():
        raise Http404
    data = event.get("data")
    email_id = data.get("email_id") if isinstance(data, dict) else None
    if not isinstance(email_id, str) or not email_id or len(email_id) > 200:
        return HttpResponse("Invalid payload", status=400)
    if InboundMessage.objects.filter(provider="resend", provider_id=email_id).exists():
        return HttpResponse(status=204)
    try:
        mail = providers.resend_fetch(email_id)
    except providers.ProviderError:
        logger.exception("Fetching mail %s from Resend failed", email_id)
        return HttpResponse("Fetching the mail failed", status=502)
    receive(mail, provider="resend", provider_id=email_id)
    return HttpResponse(status=204)
