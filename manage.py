#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from speckenv import read_speckenv


if __name__ == "__main__":
    read_speckenv(Path(__file__).parent / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "biwak.settings")
    # The audit log's name for what a command changes, migrations too
    # (PostgreSQL's application_name; jobs and requests set their own with
    # set_user_name(), specs/auditing.md)
    os.environ.setdefault("PGAPPNAME", " ".join(["manage.py", *sys.argv[1:2]]))

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
