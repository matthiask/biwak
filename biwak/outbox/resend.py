"""anymail's Resend backend with what the outbox needs (specs/mail-sending.md):
the row's ``Idempotency-Key`` (an HTTP header of Resend's API, which anymail
doesn't set) and the kind as a tag for Resend's dashboard (Resend's own
tags; anymail's ``tags`` go into an ``X-Tags`` header). Mails without a kind
went around the outbox: ``mail_admins``, tagged ``admin``."""

from anymail.backends import resend


class ResendPayload(resend.ResendPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        headers = kwargs.pop("headers", None) or {}
        if key := getattr(message, "idempotency_key", None):
            headers["Idempotency-Key"] = key
        super().__init__(message, defaults, backend, *args, headers=headers, **kwargs)
        kind = getattr(message, "outbox_kind", None) or "admin"
        self.data["tags"] = [{"name": "kind", "value": str(kind)}]


class EmailBackend(resend.EmailBackend):
    def build_message_payload(self, message, defaults):
        return ResendPayload(message, defaults, self)
