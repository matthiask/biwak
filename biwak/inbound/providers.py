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

import dataclasses
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses


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
    value = str(values[-1]).strip()
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
