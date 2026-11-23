# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# cli/gov/skills/__init__.py, see NOTICE)
"""Claude Code skills using biwak, linked into Claude Code's skills

The skills are the directories next to this file. Links point to them
where biwak is installed: the checkout for editable installs, else uv's
environment of the tool, so that upgrading biwak upgrades them too
(specs/agent-skills.md)."""

import os
import re
from pathlib import Path

import click

from biwak_cli.commands import console, json_option, table
from biwak_cli.core import cli, echo_json


SKILLS = Path(__file__).parent


def _skills():
    return sorted(path.parent for path in SKILLS.glob("*/SKILL.md"))


def _target():
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(config) if config else Path.home() / ".claude") / "skills"


def _description(skill):
    """The frontmatter's description, on one line"""
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    return re.search(r"^description: (.*)$", text.split("---")[1], re.MULTILINE)[1]


def _ours(link):
    """Links to skills of a biwak, this one or another (an earlier
    environment, a checkout)"""
    if not link.is_symlink():
        return False
    target = Path(os.readlink(link))
    return target.parent.name == "skills" and target.parent.parent.name == "biwak_cli"


def _state(link, skill):
    if link.is_symlink():
        if Path(os.readlink(link)) == skill:
            return "linked"
        return f"linked to {os.readlink(link)}"
    if link.exists():
        return "a directory of its own"
    return "not linked"


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def skills(ctx, as_json):
    """Claude Code skills using biwak; without a command the skills and
    whether Claude Code has them"""
    if ctx.invoked_subcommand is not None:
        return None
    target = _target()
    data = [
        {
            "name": skill.name,
            "description": _description(skill),
            "path": str(skill),
            "state": _state(target / skill.name, skill),
        }
        for skill in _skills()
    ]
    if as_json:
        return echo_json(data)
    t = table("Skill", "State", "Description")
    # Only the descriptions wrap
    t.columns[0].no_wrap = t.columns[1].no_wrap = True
    for row in data:
        t.add_row(row["name"], row["state"], row["description"])
    console.print(t)
    if any(row["state"] != "linked" for row in data):
        console.print("Link them with biwak skills install.")
    return None


@skills.command()
def install():
    """Link the skills into Claude Code's skills (~/.claude/skills), again
    when biwak brings new ones (upgrading biwak updates those linked)"""
    target = _target()
    target.mkdir(parents=True, exist_ok=True)
    names = set()
    for skill in _skills():
        names.add(skill.name)
        link = target / skill.name
        if link.exists() and not link.is_symlink():
            console.print(f"{link} is a directory of its own, left alone.")
            continue
        if link.is_symlink() and Path(os.readlink(link)) == skill:
            continue
        link.unlink(missing_ok=True)
        link.symlink_to(skill, target_is_directory=True)
        console.print(f"Linked {skill.name}.")
    # Skills biwak doesn't have anymore, or links to an environment uv removed
    for link in sorted(target.iterdir()):
        if link.name not in names and _ours(link):
            link.unlink()
            console.print(f"Removed {link.name}.")
    console.print(f"The skills are in {target}.")


@skills.command()
def uninstall():
    """Remove the links to the skills"""
    target = _target()
    if target.is_dir():
        for link in sorted(target.iterdir()):
            if _ours(link):
                link.unlink()
                console.print(f"Removed {link.name}.")
