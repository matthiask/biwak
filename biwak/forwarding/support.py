"""Made-up forwarded mails for the tests (``samples/``), shaped like the
forwards of Outlook, Gmail and Apple Mail; ``IMAGEDATA`` becomes an image
large enough not to count as a signature logo"""

import base64
import textwrap
from pathlib import Path

from biwak.inbound.providers import MIN_INLINE_SIZE, parse


SAMPLES = Path(__file__).parent / "samples"
PASS = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}
# A PNG's signature and padding: large enough to be kept
IMAGE = b"\x89PNG\r\n\x1a\n" + bytes(MIN_INLINE_SIZE + 1000)


def raw_sample(name, *, replace=()):
    raw = (SAMPLES / name).read_bytes()
    image = "\n".join(textwrap.wrap(base64.b64encode(IMAGE).decode(), 76))
    raw = raw.replace(b"IMAGEDATA", image.encode())
    for old, new in replace:
        raw = raw.replace(old.encode(), new.encode())
    return raw


def sample(name, *, replace=(), auth=PASS):
    return parse(raw_sample(name, replace=replace), **auth)
