"""The kind of a link from its URL's host (specs/feed.md): a small table,
no tool is hard-coded into the core. The kinds have an icon each in
``bookmarks/_kind_icon.html``."""

from urllib.parse import urlsplit

from django.utils.translation import gettext_lazy as _


FIGMA = "figma"
GITHUB = "github"
GITLAB = "gitlab"
GOOGLE_DRIVE = "google_drive"
LINK = "link"

KINDS = {
    FIGMA: _("Figma"),
    GITHUB: _("GitHub"),
    GITLAB: _("GitLab"),
    GOOGLE_DRIVE: _("Google Drive"),
    LINK: _("link"),
}

# Hosts (and their subdomains) → kind
HOSTS = {
    "figma.com": FIGMA,
    "github.com": GITHUB,
    "gitlab.com": GITLAB,
    "docs.google.com": GOOGLE_DRIVE,
    "drive.google.com": GOOGLE_DRIVE,
}


def host_of(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def kind_for(url):
    """The kind of the URL's host or its parent domains, else ``link``"""
    parts = host_of(url).split(".")
    for start in range(len(parts)):
        if kind := HOSTS.get(".".join(parts[start:])):
            return kind
    return LINK
