"""The Basecamp API (specs/import-basecamp.md): OAuth bearer token, flat
routes, pagination by ``Link`` headers, rate limits.

Basecamp answers 429 with ``Retry-After``: wait as told. Otherwise at most
50 requests per 10 seconds. Server errors are retried with a growing wait.
The importer uses ``get()``, ``paginate()`` and ``download()``, and
``archive_project()`` with ``--archive``; the tests give it a fake client
with the same methods.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field


API = "https://3.basecampapi.com"
USER_AGENT = "Biwak importer (https://github.com/matthiask/biwak)"
# Basecamp's limit is 50 requests per 10 seconds and IP address
WINDOW = 10
LIMIT = 50
RETRIES = 5


class NotFound(Exception):
    """404: deleted, or not visible to the token's person"""


class ApiError(Exception):
    pass


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def urllib_transport(url, headers, method="GET"):
    """One request, redirects not followed (downloads redirect to a URL
    which must not get our token)"""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with opener.open(request, timeout=60) as response:
            return Response(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        # Redirects of downloads arrive as errors (not followed): closed
        # here, else Python warns about each one (ResourceWarning)
        with exc:
            return Response(exc.code, dict(exc.headers), exc.read())


class BasecampClient:
    def __init__(
        self,
        account,
        token,
        *,
        transport=urllib_transport,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.account = account
        self.token = token
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self._sent = deque()
        # For progress: requests sent, and who to tell about a wait
        # (``on_wait(seconds, why)``)
        self.request_count = 0
        self.on_wait = None

    def _sleep(self, seconds, why):
        if self.on_wait is not None and seconds >= 1:
            self.on_wait(seconds, why)
        self.sleep(seconds)

    def _wait_for_slot(self):
        now = self.clock()
        while self._sent and self._sent[0] <= now - WINDOW:
            self._sent.popleft()
        if len(self._sent) >= LIMIT:
            self._sleep(self._sent[0] + WINDOW - now, "rate limit")
        self._sent.append(self.clock())
        self.request_count += 1

    def _request(self, url, *, auth=True, accept=None, method="GET"):
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(RETRIES):
            self._wait_for_slot()
            response = self.transport(url, headers, method=method)
            if response.status == 429:
                wait = int(_header(response, "Retry-After") or WINDOW)
                self._sleep(wait, "Basecamp asked to wait (429)")
                continue
            if response.status >= 500:
                self._sleep(2**attempt, f"server error {response.status}, retrying")
                continue
            return response
        raise ApiError(f"Giving up on {url}: status {response.status}")

    def _url(self, path, params):
        url = path if path.startswith("http") else f"{API}/{self.account}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return url

    def _json(self, url):
        response = self._request(url)
        if response.status == 404:
            raise NotFound(url)
        if response.status != 200:
            raise ApiError(f"{url}: status {response.status}")
        return response

    def get(self, path, **params):
        return json.loads(self._json(self._url(path, params)).body)

    def paginate(self, path, **params):
        """All items of a collection, following the ``Link: rel="next"``"""
        url = self._url(path, params)
        while url:
            response = self._json(url)
            yield from json.loads(response.body)
            link = _header(response, "Link") or ""
            found = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = found[1] if found else None

    def archive_project(self, project_id):
        """Archives the project in Basecamp. Accounts may limit archiving
        to administrators and the project's creator (403)."""
        url = self._url(f"/projects/{project_id}/status/archived.json", None)
        response = self._request(url, method="PUT")
        if response.status == 404:
            raise NotFound(url)
        if response.status == 403:
            raise ApiError(f"{url}: not allowed to archive the project (403)")
        if response.status not in {200, 204}:
            raise ApiError(f"{url}: status {response.status}")

    def download(self, url, *, accept=None):
        """The file's bytes: the API redirects to a short-lived URL, which
        doesn't get the token. ``accept`` is the ``Accept`` header."""
        response = self._request(url, accept=accept)
        if response.status in {301, 302, 303, 307, 308}:
            response = self._request(
                _header(response, "Location"), auth=False, accept=accept
            )
        if response.status == 404:
            raise NotFound(url)
        if response.status != 200:
            raise ApiError(f"{url}: status {response.status}")
        return response.body


def _header(response, name):
    for key, value in response.headers.items():
        if key.lower() == name.lower():
            return value
    return None
