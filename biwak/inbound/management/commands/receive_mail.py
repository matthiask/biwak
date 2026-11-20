import hashlib
from pathlib import Path

from django.core.management import BaseCommand

from biwak.inbound.providers import parse
from biwak.inbound.receive import receive


RESULTS = ["pass", "fail", "gray", "processing_failed", "unknown"]


class Command(BaseCommand):
    help = (
        "Handles a mail (an .eml file) like a reply received through the"
        " provider, for tests and debugging. The authentication results are"
        " what the receiving server would report: they're never read from"
        " the mail's headers, and are 'unknown' unless given."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        for name in ("spf", "dkim", "dmarc"):
            parser.add_argument(f"--{name}", choices=RESULTS, default="unknown")

    def handle(self, file, **options):
        raw = file.read_bytes()
        mail = parse(
            raw, spf=options["spf"], dkim=options["dkim"], dmarc=options["dmarc"]
        )
        message = receive(
            mail, provider="file", provider_id=hashlib.sha256(raw).hexdigest()
        )
        if message is None:
            self.stdout.write("Received before, nothing done.")
        else:
            self.stdout.write(f"{message.get_status_display()} {message.error}".strip())
