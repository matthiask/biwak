"""The German catalog (specs/languages.md, "Checks"): complete, compiled,
up to date with the code, and following the glossary"""

import ast
import gettext
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


LOCALE = settings.BASE_DIR / "conf" / "locale"
PO = LOCALE / "de" / "LC_MESSAGES" / "django.po"
MO = PO.with_suffix(".mo")
HAS_GETTEXT = shutil.which("msgfmt") is not None

# What `fl mm -l de` runs (fh_fablib), so a run here finds what it would
MAKEMESSAGES = {
    "locale": ["de"],
    "add_location": "file",
    "no_wrap": True,
    "ignore_patterns": [
        ".venv",
        "htmlcov",
        "node_modules",
        "lib",
        "build",
        "dist",
        "tmp",
    ],
    "verbosity": 0,
}


def entries(path):
    """``{(context, msgid): [msgstr, …]}`` of a ``.po`` file, without the
    header and obsolete entries, and the fuzzy ones' keys"""
    found, fuzzy = {}, set()
    block = []
    for line in [*path.read_text().splitlines(), ""]:
        if line.strip():
            block.append(line)
            continue
        if block:
            key, strings = _entry(block)
            if key is not None and key != (None, ""):
                found[key] = strings
                if any(b.startswith("#,") and "fuzzy" in b for b in block):
                    fuzzy.add(key)
        block = []
    return found, fuzzy


_STRING = re.compile(r'^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?) "(.*)"$')


def _entry(block):
    if any(line.startswith("#~") for line in block):
        return None, None
    fields, current = {}, None
    for line in block:
        if match := _STRING.match(line):
            current = match[1]
            fields[current] = match[2]
        elif line.startswith('"') and current:
            fields[current] += line[1:-1]
    if "msgid" not in fields:
        return None, None
    strings = [value for name, value in fields.items() if name.startswith("msgstr")]
    return (fields.get("msgctxt"), fields["msgid"]), strings


class CatalogTest(SimpleTestCase):
    def test_complete_without_fuzzy_entries(self):
        found, fuzzy = entries(PO)
        self.assertGreater(len(found), 1000)
        self.assertEqual(sorted(fuzzy), [])
        empty = [key for key, strings in found.items() if not all(strings)]
        self.assertEqual(empty, [])

    @skipUnless(HAS_GETTEXT, "msgfmt is missing (gettext)")
    def test_msgfmt_check_and_the_mo_file_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            compiled = Path(directory) / "django.mo"
            subprocess.run(
                ["msgfmt", "--check", "-o", str(compiled), str(PO)],
                check=True,
                capture_output=True,
            )
            with compiled.open("rb") as fresh, MO.open("rb") as committed:
                self.assertEqual(
                    gettext.GNUTranslations(fresh)._catalog,
                    gettext.GNUTranslations(committed)._catalog,
                    "Run `fl cm` (compilemessages) and commit the .mo file.",
                )

    @skipUnless(HAS_GETTEXT, "xgettext is missing (gettext)")
    def test_every_text_of_the_code_is_in_the_catalog(self):
        """``makemessages`` on a copy adds nothing: every marked text is
        translated (run ``fl mm -l de`` and translate the new entries)"""
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "locale"
            shutil.copytree(LOCALE, copy)
            with override_settings(LOCALE_PATHS=[copy]):
                call_command("makemessages", **MAKEMESSAGES)
            fresh, _fuzzy = entries(copy / "de" / "LC_MESSAGES" / "django.po")
        known, _fuzzy = entries(PO)
        self.assertEqual(sorted(set(fresh) - set(known), key=str), [])


# The glossary's words the catalog doesn't use (specs/languages.md): its
# German replaces them. Whole words, any case.
AVOIDED = {
    "ß": "Swiss spelling: ss",
    # Any word with it: "Partner:in", "Partnerorganisation"
    "Partner": "Externe, extern",
    "Aufgabe": "To-do",
    "Aufgaben": "To-dos",
    "Kunde": "Kund:in",
    "Kunden": "Kund:innen",
    "Kundin": "Kund:in",
    "Kundinnen": "Kund:innen",
    "Abonnenten": "Abonnent:innen",
    "Feed": "Aktivität",
    "Nachricht": "Mitteilung",
    "Nachrichten": "Mitteilungen",
    "Mülleimer": "Papierkorb",
    "Lesezeichen setzen": "Lesezeichen",
    "einloggen": "anmelden",
    "ausloggen": "abmelden",
    "Login": "Anmeldung",
    "Logout": "Abmeldung",
    "Mitarbeiter": "Mitarbeitende",
    "Teilnehmer": "Teilnehmer:innen",
    "Benutzer": "Person",
    "Sie": "du",
    "Ihre": "deine",
    "Ihr": "dein",
    "Ihnen": "dir",
    "Kommandopalette": "Befehlspalette",
}


def _avoided(text):
    found = []
    for word, instead in AVOIDED.items():
        if word in {"ß", "Partner"}:
            if word.lower() in text.lower():
                found.append((word, instead))
            continue
        # Formal address is capitalized mid-sentence; at a sentence's start
        # "Sie"/"Ihr" would be "sie"/"ihr" (they) anyway, which never start
        # our sentences
        flags = 0 if word in {"Sie", "Ihre", "Ihr", "Ihnen"} else re.IGNORECASE
        if re.search(rf"(?<![\w:]){re.escape(word)}(?![\w:])", text, flags):
            found.append((word, instead))
    return found


class GlossaryTest(SimpleTestCase):
    def test_the_catalog_follows_the_glossary(self):
        found, _fuzzy = entries(PO)
        wrong = {
            msgid: _avoided(" ".join(strings))
            for (_context, msgid), strings in found.items()
            if _avoided(" ".join(strings))
        }
        self.assertEqual(wrong, {})

    def test_the_check_finds_them(self):
        self.assertEqual(_avoided("Grösse"), [])
        self.assertEqual(_avoided("Grüße"), [("ß", "Swiss spelling: ss")])
        self.assertEqual(_avoided("Neue Aufgabe"), [("Aufgabe", "To-do")])
        self.assertEqual(_avoided("Für Kund:innen sichtbar"), [])
        self.assertEqual(_avoided("Teilnehmer:innen"), [])
        self.assertEqual(_avoided("Eine Partner:in"), [("Partner", "Externe, extern")])
        self.assertEqual(_avoided("Ada ist extern"), [])
        self.assertEqual(_avoided("Hast du Zeit?"), [])
        self.assertEqual(_avoided("Haben Sie Zeit?"), [("Sie", "du")])


_EAGER = {"gettext", "ngettext", "pgettext", "npgettext"}


def _eager_calls(path):
    """Lines calling ``gettext()`` and friends outside of functions: run at
    import, they'd stay in the language active then (English)"""
    tree = ast.parse(path.read_text())
    names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "django.utils.translation"
        for alias in node.names
        if alias.name in _EAGER
    }
    found = []

    def visit(node, *, in_function):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            in_function = True
        if (
            not in_function
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in names
        ):
            found.append(f"{path.relative_to(settings.BASE_DIR)}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            visit(child, in_function=in_function)

    visit(tree, in_function=False)
    return found


class ImportTimeTest(SimpleTestCase):
    def test_no_gettext_at_import(self):
        """Labels of forms and models, constants: ``gettext_lazy``"""
        found = [
            line
            for path in sorted((settings.BASE_DIR / "biwak").rglob("*.py"))
            if "migrations" not in path.parts
            and not path.name.startswith("test_")
            # makemessages' temporary copies of templates (403.html.py)
            and "." not in path.stem
            for line in _eager_calls(path)
        ]
        self.assertEqual(found, [])
