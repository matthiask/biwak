"""Made-up mails for the tests, shaped like those of Gmail, Outlook,
Apple Mail and phones (``samples/``), with the reply token
``replytoken0000000000`` to replace"""

import itertools
from pathlib import Path

from biwak.inbound.providers import parse
from biwak.inbound.receive import receive


SAMPLES = Path(__file__).parent / "samples"
PLACEHOLDER = b"replytoken0000000000"
PASS = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}

_ids = itertools.count()


def raw_sample(name, token=None, *, replace=()):
    """The sample's bytes with the token (a ``ReplyToken`` or a string)"""
    raw = (SAMPLES / name).read_bytes()
    if token is not None:
        value = token if isinstance(token, str) else token.token
        raw = raw.replace(PLACEHOLDER, value.encode())
    for old, new in replace:
        raw = raw.replace(old.encode(), new.encode())
    return raw


def sample(name, token=None, *, replace=(), auth=PASS):
    return parse(raw_sample(name, token, replace=replace), **auth)


class ReceiveMixin:
    def receive(self, mail, *, provider_id=None, now=None):
        """Receives the mail, answers (after the commit) included"""
        with self.captureOnCommitCallbacks(execute=True):
            return receive(
                mail,
                provider="test",
                provider_id=provider_id or f"test-{next(_ids)}",
                now=now,
            )
