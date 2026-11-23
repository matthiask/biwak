"""The Biwak CLI, `biwak <command>`"""

from biwak_cli import commands, skills  # noqa: F401 Registers the commands
from biwak_cli.core import cli


__all__ = ["cli"]
