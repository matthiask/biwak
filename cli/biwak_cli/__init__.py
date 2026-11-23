"""The Biwak CLI, `biwak <command>`"""

from biwak_cli import (  # noqa: F401 Register the commands
    account,
    checkins,
    feed,
    files,
    links,
    messages,
    notifications,
    people,
    projects,
    skills,
    todos,
)
from biwak_cli.core import cli


__all__ = ["cli"]
