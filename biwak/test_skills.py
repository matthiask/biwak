# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# governance/test_skills.py and governance/test_cli.py, see NOTICE)
"""The agent skills in the CLI (specs/agent-skills.md)"""

import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import biwak_cli
import click
from click.testing import CliRunner
from django.conf import settings
from django.test import SimpleTestCase


SKILLS = settings.BASE_DIR / "cli" / "biwak_cli" / "skills"
NAMES = ["biwak-from-mail", "biwak-triage"]


def biwak_commands(text):
    """The words of the `biwak` commands in a skill: lines of code blocks
    starting with it, and inline code, up to a comment"""
    lines = re.findall(r"^\s*(biwak [^\n#]*)", text, re.MULTILINE)
    lines += re.findall(r"`(biwak [^`#]*)`", text)
    for line in lines:
        yield [word for word in line.split() if word != "\\"]


class SkillTest(SimpleTestCase):
    def test_skills(self):
        """The skills with their name and a description of when to use them"""
        paths = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertEqual([path.parent.name for path in paths], NAMES)
        for path in paths:
            with self.subTest(skill=path.parent.name):
                frontmatter = path.read_text().split("---")[1]
                self.assertIn(f"\nname: {path.parent.name}\n", frontmatter)
                self.assertRegex(frontmatter, r"\ndescription: .*Use when")

    def test_biwak_commands(self):
        """The commands, options and choices the skills show exist"""
        checked = 0
        for path in sorted(SKILLS.glob("*/SKILL.md")):
            for words in biwak_commands(path.read_text()):
                with self.subTest(skill=path.parent.name, command=" ".join(words)):
                    command = biwak_cli.cli
                    rest = iter(words[1:])
                    for word in rest:
                        if word in {"<", "|", ">", "--help"}:
                            break
                        if len(word) > 1 and word.startswith("-"):  # Not stdin
                            options = {
                                opt: param
                                for param in command.params
                                for opt in param.opts + param.secondary_opts
                            }
                            self.assertIn(word, options)
                            param = options[word]
                            if not param.is_flag:
                                value = next(rest)  # Its value
                                if isinstance(param.type, click.Choice) and not (
                                    value.startswith("<")
                                ):
                                    self.assertIn(value, param.type.choices)
                        elif isinstance(command, click.Group):
                            # Groups take no arguments, only their commands
                            self.assertIn(word, command.commands)
                            command = command.commands[word]
                    checked += 1
        self.assertGreaterEqual(checked, 5 * len(NAMES))


class InstallTest(SimpleTestCase):
    """`biwak skills install` with a temporary home, and skills of its own
    (where biwak is installed: a checkout or uv's environment)"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.skills = self.directory / "home" / ".claude" / "skills"
        self.ours = self.directory / "env" / "biwak_cli" / "skills"
        for name in ["biwak-one", "biwak-two", "biwak-three"]:
            (self.ours / name).mkdir(parents=True)
            (self.ours / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Does {name}. Use when asked.\n---\n"
            )
        for patcher in [
            patch.dict("os.environ", {"HOME": str(self.directory / "home")}),
            patch.object(biwak_cli.skills, "SKILLS", self.ours),
            patch.object(biwak_cli.commands.console, "_width", 200),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def biwak(self, *args):
        result = CliRunner().invoke(biwak_cli.cli, args, catch_exceptions=False)
        self.assertEqual(result.exit_code, 0, result.output)
        return result

    def test_install(self):
        """Linking the skills into Claude Code's skills, replacing stale links
        and leaving directories of their own alone"""
        self.skills.mkdir(parents=True)
        # Linked from an environment uv removed, a skill biwak doesn't have
        # anymore, somebody's own skill and somebody's own directory
        gone = self.directory / "old" / "biwak_cli" / "skills"
        (self.skills / "biwak-one").symlink_to(gone / "biwak-one")
        (self.skills / "biwak-gone").symlink_to(gone / "biwak-gone")
        (self.skills / "mine").symlink_to(self.directory)
        (self.skills / "biwak-three").mkdir()

        output = self.biwak("skills").output
        self.assertIn("Does biwak-two. Use when asked.", output)
        self.assertIn("not linked", output)
        self.assertIn("biwak skills install", output)

        output = self.biwak("skills", "install").output
        self.assertIn("Linked biwak-one.", output)
        self.assertIn("Linked biwak-two.", output)
        self.assertIn("Removed biwak-gone.", output)
        self.assertIn("biwak-three is a directory of its own", output)
        self.assertEqual(
            (self.skills / "biwak-one").readlink(), self.ours / "biwak-one"
        )
        self.assertTrue((self.skills / "biwak-two" / "SKILL.md").exists())
        self.assertFalse((self.skills / "biwak-gone").is_symlink())
        self.assertTrue((self.skills / "mine").is_symlink())

        # Nothing to do the second time
        self.assertNotIn("Linked", self.biwak("skills", "install").output)

        data = json.loads(self.biwak("skills", "--json").output)
        self.assertEqual(
            {skill["name"]: skill["state"] for skill in data},
            {
                "biwak-one": "linked",
                "biwak-three": "a directory of its own",
                "biwak-two": "linked",
            },
        )

        self.biwak("skills", "uninstall")
        self.assertEqual(
            sorted(path.name for path in self.skills.iterdir()),
            ["biwak-three", "mine"],
        )

    def test_install_creates_the_directory(self):
        """A Claude Code without skills yet; CLAUDE_CONFIG_DIR moves them"""
        self.biwak("skills", "install")
        self.assertEqual(
            sorted(path.name for path in self.skills.iterdir()),
            ["biwak-one", "biwak-three", "biwak-two"],
        )
        config = self.directory / "config"
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(config)}):
            self.biwak("skills", "install")
        self.assertTrue((config / "skills" / "biwak-one").is_symlink())
