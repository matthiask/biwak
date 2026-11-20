import io
import tempfile
from pathlib import Path

from django.core.management import call_command

from biwak.inbound.models import InboundMessage, InboundStatus
from biwak.inbound.support import ReplyTestCase
from biwak.inbound.support_mails import raw_sample


class ReceiveMailCommandTest(ReplyTestCase):
    def call(self, path, *args):
        out = io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("receive_mail", str(path), *args, stdout=out)
        return out.getvalue().strip()

    def test_results_are_given_never_read_from_the_mail(self):
        token = self.token()
        path = self.tmp("spoofed.eml", token)
        self.assertEqual(self.call(path), "authentication failed")
        path = self.tmp("gmail_en.eml", token)
        self.assertEqual(self.call(path, "--dmarc", "pass"), "posted")
        self.assertEqual(
            self.call(path, "--dmarc", "pass"), "Received before, nothing done."
        )
        self.assertEqual(
            list(
                InboundMessage.objects.order_by("pk").values_list("provider", "status")
            ),
            [("file", InboundStatus.UNAUTHENTICATED), ("file", InboundStatus.POSTED)],
        )
        self.assertEqual(len(self.comments()), 1)

    def tmp(self, name, token):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / name
        path.write_bytes(raw_sample(name, token))
        return path
