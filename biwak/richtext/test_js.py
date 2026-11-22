"""The editor's JavaScript tests (``frontend/editor/tests/*.test.js``,
Node's own test runner) as part of the Django tests"""

import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from biwak.richtext.test_parity import NODE, available


class JavaScriptTest(SimpleTestCase):
    def test_node_tests(self):
        if not available():
            self.skipTest("Node or node_modules missing")
        result = subprocess.run(
            [NODE, "--test", str(Path("frontend") / "editor" / "tests")],
            check=False,
            capture_output=True,
            text=True,
            cwd=settings.BASE_DIR,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
