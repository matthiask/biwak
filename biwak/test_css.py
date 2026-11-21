"""Every class a template uses is either in the built stylesheet or a
hook on purpose (a script or a test selects it)

Bootstrap is compiled in parts (``frontend/styles/bootstrap.scss``), so a
utility nobody compiled does nothing: no error, just a page that looks
wrong. Needs the production bundle ``./runtests.sh`` builds first.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


# Classes without CSS: selectors of tests, markers
HOOKS = {
    "wb-group-name",
    "wb-links",
    "wb-completed",
    "wb-peek",
}

TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)


def template_classes():
    used = {}
    for path in (settings.BASE_DIR / "biwak").rglob("templates/**/*.html"):
        for match in re.finditer(r'class="([^"]*)"', path.read_text()):
            # A class partly made by a tag (alert-{{ tag }}) can't be checked
            value = TAG.sub("\0", match.group(1))
            for name in value.split():
                if "\0" not in name:
                    used.setdefault(name, path.name)
    return used


class StylesheetTest(SimpleTestCase):
    def test_every_class_of_the_templates_is_in_the_stylesheet(self):
        sheets = list(Path(settings.STATIC_ROOT).glob("main.*.css"))
        if not sheets:  # pragma: no cover
            self.skipTest("No bundle: yarn rspack build --mode production")
        css = re.sub(r'"[^"]*"', "", sheets[0].read_text())
        defined = set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css))
        missing = {
            name: path
            for name, path in template_classes().items()
            if name not in defined and name not in HOOKS
        }
        self.assertEqual(missing, {})
