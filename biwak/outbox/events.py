"""What Resend's webhooks report about the mails we sent
(specs/mail-sending.md): delivered, bounced, marked as spam. A hard bounce
or a complaint marks the address undeliverable (``User.mail_undeliverable_at``):
no more notification mails, digests and check-in mails go to it."""

import logging
from email.utils import parseaddr

from django.db import transaction
from django.utils import timezone

from biwak.accounts.models import User
from biwak.outbox.models import Delivery, OutgoingMail


logger = logging.getLogger(__name__)

EVENTS = {
    "email.delivered": Delivery.DELIVERED,
    "email.bounced": Delivery.BOUNCED,
    "email.complained": Delivery.COMPLAINED,
}
# The worst so far stays: a complaint after the delivery, not the other way
RANK = {"": 0, Delivery.DELIVERED: 1, Delivery.BOUNCED: 2, Delivery.COMPLAINED: 3}


def _addresses(values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return set()
    return {
        parseaddr(value)[1].lower() for value in values if isinstance(value, str)
    } - {""}


def record(event, *, now=None):
    """Records a delivery event (Resend's webhook payload, its signature
    checked); returns whether it was about a mail of ours"""
    now = now or timezone.now()
    data = event.get("data")
    if not isinstance(data, dict):
        return False
    email_id = data.get("email_id")
    if not isinstance(email_id, str) or not email_id:
        return False
    delivery = EVENTS[event["type"]]
    bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
    # Resend: "Permanent" or "Temporary"; only a permanent one is hard
    hard = delivery == Delivery.COMPLAINED or (
        delivery == Delivery.BOUNCED and bounce.get("type") == "Permanent"
    )
    with transaction.atomic():
        row = (
            OutgoingMail.objects
            .select_for_update()
            .filter(provider_id=email_id)
            .first()
        )
        if row is None:
            # Not ours (another app on the account), or deleted after
            # ``sending.RETENTION``
            return False
        if delivery == Delivery.BOUNCED:
            row.delivery_detail = " ".join(
                str(bounce.get(key) or "") for key in ("type", "subType", "message")
            ).strip()[:2000]
        if (delivery != Delivery.BOUNCED or hard) and RANK[delivery] >= RANK[
            row.delivery
        ]:
            row.delivery = delivery
            row.delivery_at = now
        row.save()
        if hard:
            recipients = {address.lower() for address in row.recipients}
            # The addresses Resend names, if they're the mail's
            addresses = (_addresses(data.get("to")) & recipients) or recipients
            for address in addresses:
                marked = User.objects.filter(
                    email__iexact=address, mail_undeliverable_at__isnull=True
                ).update(mail_undeliverable_at=now)
                if marked:
                    logger.warning(
                        "Mail to %s is undeliverable (%s)", address, delivery
                    )
    return True
