"""Telling users of the biwak command line interface (cli/) to upgrade:
versioned with the server, it warns when they don't match
(specs/api-cli.md)"""

import tomllib

from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext as _


# Raise this when the API changes in ways older CLIs can't handle
# (0.20.0: docs without locks, specs/collaboration.md; older CLIs take a
# lock that isn't there anymore and fail; 0.30.0: links on projects only,
# the links list has no ``item_id`` anymore, specs/feed.md; 0.46.0: check-in
# questions have no ``time_zone`` anymore, specs/checkins.md; 0.60.0: the
# commands renamed in the style of gov and wb, specs/cli-style.md, and
# search without templates; 0.66.0: new domains of an organization ask
# whether people without one at them move along, specs/organizations.md)
MINIMUM = (0, 66, 0)
INSTALL = "git+https://github.com/matthiask/biwak#subdirectory=cli"
_PROJECT = tomllib.loads((settings.BASE_DIR / "cli" / "pyproject.toml").read_text())[
    "project"
]
LATEST = _PROJECT["version"]
UPGRADE = f"uv tool install --upgrade '{INSTALL}'"
HEADER = "X-Biwak-CLI"


def _parse(version):
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


def cli_version_middleware(get_response):
    """Reject CLIs which are too old, tell outdated ones about the latest
    version"""

    def middleware(request):
        if not (version := request.headers.get(HEADER)):
            return get_response(request)
        if _parse(version) < MINIMUM:
            return JsonResponse(
                {
                    "detail": _("Your biwak is too old, please upgrade it: %(command)s")
                    % {"command": UPGRADE}
                },
                status=426,
            )
        response = get_response(request)
        response[f"{HEADER}-Latest"] = LATEST
        response[f"{HEADER}-Upgrade"] = UPGRADE
        return response

    return middleware
