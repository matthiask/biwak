"""Configuration, logging in and talking to the API"""

import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
import tomllib
import webbrowser
from functools import cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import click
import requests
import tomli_w


CONFIG = Path.home() / ".config" / "biwak.toml"
LOGIN_TIMEOUT = 300


def _version():
    """The checkout's version for editable installs"""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject.exists():
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    return version("biwak-cli")


VERSION = _version()


def terminate(msg):
    click.echo(msg, file=sys.stderr)
    sys.exit(1)


def base_url(url):
    """Scheme and host; URLs may be pasted from the browser"""
    if not url:
        return url
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}"


def read_config():
    return tomllib.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def write_config(config):
    """Readable by the owner only (mkstemp), replaced in one go"""
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=CONFIG.parent, prefix=f".{CONFIG.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(tomli_w.dumps({k: v for k, v in config.items() if v}))
        os.replace(path, CONFIG)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def current():
    """URL and token: the environment first, then the stored login"""
    config = read_config()
    url = base_url(os.environ.get("BIWAK_URL") or config.get("url"))
    token = os.environ.get("BIWAK_TOKEN") or config.get("token")
    if not url or not token:
        terminate("Not logged in. Run `biwak login URL --read` or `--write`.")
    return url, token


def browser_login(url, access):
    """Biwak posts a new token to a server on a local port; the state
    protects against tokens posted by others"""
    state = secrets.token_urlsafe(24)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", 0))
            data = parse_qs(self.rfile.read(length).decode())
            if data.get("state") != [state] or not data.get("token"):
                self.send_error(400)
                return
            result["token"] = data["token"][0]
            body = b"biwak is authorized. You can close this window."
            self.send_response(200)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    login_url = (
        urljoin(url, "/accounts/cli-login/")
        + "?"
        + urlencode({
            "port": server.server_address[1],
            "state": state,
            "name": socket.gethostname(),
            "access": access,
        })
    )
    click.echo(f"Authorize biwak in your browser: {login_url}", err=True)
    threading.Thread(target=webbrowser.open, args=[login_url], daemon=True).start()
    deadline = time.monotonic() + LOGIN_TIMEOUT
    with server:
        while "token" not in result and time.monotonic() < deadline:
            server.handle_request()
    if "token" not in result:
        terminate("Timed out waiting for the browser.")
    save_login(url, result["token"], access)
    return result["token"]


def save_login(url, token, access=None):
    write_config({"url": url, "token": token, "access": access})
    click.echo(f"Saved {CONFIG}", err=True)


def _parse_version(value):
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


@cache
def _check_version(latest, upgrade):
    """Once per run: a newer CLI exists, or the server is older"""
    if not latest:
        return
    if _parse_version(latest) > _parse_version(VERSION):
        click.secho(
            f"biwak {latest} is available (you have {VERSION}): {upgrade}",
            fg="yellow",
            err=True,
        )
    elif _parse_version(latest) < _parse_version(VERSION):
        click.secho(
            f"This Biwak is older than your biwak ({latest} < {VERSION}),"
            " some commands may fail until it's updated.",
            fg="yellow",
            err=True,
        )


def _send(method, url, path, token, **kwargs):
    try:
        return requests.request(
            method,
            urljoin(url, f"/api/v1/{path}"),
            headers={"authorization": f"Bearer {token}", "x-biwak-cli": VERSION},
            **{"timeout": 30} | kwargs,
        )
    except requests.RequestException as exc:
        terminate(str(exc))


def request(method, path, **kwargs):
    """The API's JSON, or terminate with its error. An expired token is
    replaced through the browser with the same access, in a terminal."""
    url, token = current()
    response = _send(method, url, path, token, **kwargs)
    access = read_config().get("access")
    if response.status_code == 401 and access and sys.stdin.isatty():
        click.secho("Your access has expired.", fg="yellow", err=True)
        token = browser_login(url, access)
        response = _send(method, url, path, token, **kwargs)
    _check_version(
        response.headers.get("x-biwak-cli-latest"),
        response.headers.get("x-biwak-cli-upgrade"),
    )
    if response.status_code == 401:
        terminate("Not authorized (anymore). Run `biwak login` again.")
    if response.status_code == 422:
        errors = response.json()["detail"]
        terminate(
            "\n".join(
                f"{'.'.join(str(p) for p in e['loc'][2:])}: {e['msg']}".lstrip(": ")
                for e in errors
            )
        )
    if not response.ok:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        terminate(
            f"{response.status_code}: {detail or ' '.join(response.text.split())[:200]}"
        )
    return response.json()


# The API's largest page (biwak/api_conventions.py)
MAX_PAGE_SIZE = 200


def paginate(path, params=None, *, limit=None):
    """The results of a list with cursor pagination, following ``next``
    page by page: all of them, or the first ``limit``"""
    params = dict(params or {})
    params["page_size"] = min(limit or MAX_PAGE_SIZE, MAX_PAGE_SIZE)
    results = []
    while limit is None or len(results) < limit:
        data = request("GET", path, params=params)
        results += data["results"]
        if not data["next"]:
            break
        # "next" is the URL of the next page
        params["cursor"] = parse_qs(urlsplit(data["next"]).query)["cursor"][0]
    return results[:limit]


def download(path, target):
    """Saves the API's file download (``path``, following the redirect to
    a presigned URL with a bucket) to ``target``"""
    url, token = current()
    response = _send("GET", url, path, token, stream=True, timeout=300)
    _check_version(
        response.headers.get("x-biwak-cli-latest"),
        response.headers.get("x-biwak-cli-upgrade"),
    )
    if not response.ok:
        terminate(f"{response.status_code}: couldn't download the file.")
    with open(target, "wb") as file:
        file.writelines(response.iter_content(64 * 1024))


def echo_json(data):
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


@click.group()
@click.version_option(VERSION, prog_name="biwak")
def cli():
    """Biwak from the command line: projects, lists and to-dos

    Items visible to clients are marked [clients]. Every command takes
    --json for scripts and agents."""
