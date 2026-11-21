"""Where replies come from (specs/notifications.md, stage 2)

A provider's adapter turns what it delivers into one ``InboundMail``; the
rest (``biwak.inbound.receive``) doesn't know providers. Resend posts a
signed webhook (Svix signatures) with metadata only; the mail itself and
the SPF, DKIM and DMARC results of its receiving servers are fetched
through its API (``GET /emails/receiving/{id}``, the original message
from ``raw.download_url``).

Only the authentication results come from the provider, never from the
mail's headers: the sender writes those.
"""

import base64
import dataclasses
import hashlib
import hmac
import json
import time
import urllib.request
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from urllib.parse import quote

from django.conf import settings


@dataclasses.dataclass
class Attachment:
    name: str
    content_type: str
    content: bytes


@dataclasses.dataclass
class InboundMail:
    """A mail received. ``sender`` is the address of the ``From`` header
    (empty unless there's exactly one); ``envelope_sender`` the bounce
    address (``""`` when empty, ``None`` when unknown); ``spf``, ``dkim``
    and ``dmarc`` what the receiving server reports (``pass``, ``fail``,
    ``gray``, ``processing_failed``, ``unknown``)."""

    sender: str
    recipients: list
    headers: EmailMessage
    text: str
    html: str
    attachments: list
    spf: str = "unknown"
    dkim: str = "unknown"
    dmarc: str = "unknown"
    envelope_sender: str | None = None

    def header(self, name):
        return str(self.headers.get(name, "") or "")

    @property
    def message_id(self):
        return self.header("Message-ID").strip()

    @property
    def subject(self):
        return " ".join(self.header("Subject").split())


def _address(value):
    """The one address of a header, lowercased; empty for none, several or
    nonsense"""
    addresses = [a for _name, a in getaddresses([value]) if "@" in a]
    return addresses[0].lower() if len(addresses) == 1 else ""


def from_address(message):
    """The ``From`` header's address, if there's exactly one ``From`` with
    exactly one address"""
    values = message.get_all("From") or []
    return _address(str(values[0])) if len(values) == 1 else ""


def _envelope_sender(message):
    values = message.get_all("Return-Path")
    if not values:
        return None
    # The receiving server's is the topmost
    value = str(values[0]).strip()
    return "" if value in {"", "<>"} else _address(value)


def _text(part):
    try:
        return part.get_content()
    except LookupError, UnicodeError, AssertionError:
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def parse(raw, **kwargs):
    """``InboundMail`` from the original message (bytes); ``kwargs`` are
    what the provider reports (``spf``, ``dkim``, ``dmarc``, more
    ``recipients``)"""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    extra = kwargs.pop("recipients", ())
    recipients = [
        a.lower()
        for _name, a in getaddresses([
            str(v)
            for name in ("To", "Cc", "Delivered-To", "X-Original-To")
            for v in message.get_all(name) or []
        ])
        if "@" in a
    ]
    recipients += [a.lower() for a in extra if a.lower() not in recipients]

    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    attachments = []
    for part in message.walk():
        if part.is_multipart() or part is text_part or part is html_part:
            continue
        name = part.get_filename()
        if not name:
            continue
        attachments.append(
            Attachment(
                name=name,
                content_type=part.get_content_type(),
                content=part.get_payload(decode=True) or b"",
            )
        )
    return InboundMail(
        sender=from_address(message),
        recipients=recipients,
        headers=message,
        text=_text(text_part) if text_part else "",
        html=_text(html_part) if html_part else "",
        attachments=attachments,
        envelope_sender=_envelope_sender(message),
        **kwargs,
    )


# Resend ----------------------------------------------------------------------


class ProviderError(Exception):
    """The provider couldn't be asked; the webhook fails and is retried"""


# Svix rejects webhooks older or newer than this, so do we
TOLERANCE = 5 * 60


def verify_svix(secret, headers, body, *, now=None):
    """Whether the webhook is signed with ``secret`` (``whsec_...``): an
    HMAC-SHA256 of ``id.timestamp.body``, base64, one of the
    space-separated ``v1,...`` signatures, the timestamp within 5
    minutes"""
    msg_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if not (secret and msg_id and timestamp and signatures):
        return False
    try:
        if abs((now or time.time()) - int(timestamp)) > TOLERANCE:
            return False
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except ValueError:
        return False
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest())
    return any(
        hmac.compare_digest(expected, signature.encode())
        for version, _comma, signature in (
            entry.partition(",") for entry in signatures.split()
        )
        if version == "v1"
    )


API = "https://api.resend.com"


def _get(url, *, auth=True):
    request = urllib.request.Request(url, headers={"User-Agent": "biwak"})
    if auth:
        request.add_header("Authorization", f"Bearer {settings.RESEND_API_KEY}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except OSError as exc:
        raise ProviderError(f"{url.split('?')[0]}: {exc}") from exc


def resend_fetch(email_id):
    """The received mail with Resend's authentication results"""
    answer = _get(f"{API}/emails/receiving/{quote(email_id, safe='')}")
    try:
        data = json.loads(answer)
    except ValueError as exc:
        raise ProviderError(f"Resend's answer for {email_id} isn't JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"Resend's answer for {email_id} isn't an object")
    raw = data.get("raw") or {}
    if not raw.get("download_url"):
        raise ProviderError(f"Resend has no original message for {email_id}")
    authentication = data.get("authentication") or {}
    mail = parse(
        _get(raw["download_url"], auth=False),
        recipients=[
            *(data.get("to") or []),
            *(data.get("cc") or []),
        ],
        **{
            key: str(authentication.get(key) or "unknown")
            for key in ("spf", "dkim", "dmarc")
        },
    )
    # Resend checked the From it parsed: if ours differs, its verdicts
    # aren't about our sender ("Name <address>" or the bare address)
    if parseaddr(str(data.get("from") or ""))[1].lower() != mail.sender:
        mail.spf = mail.dkim = mail.dmarc = "unknown"
    return mail
