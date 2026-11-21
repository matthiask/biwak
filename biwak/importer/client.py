"""The Basecamp API (specs/import-basecamp.md): OAuth bearer token, flat
routes, pagination by ``Link`` headers, rate limits.

Basecamp answers 429 with ``Retry-After``: wait as told. Otherwise at most
50 requests per 10 seconds. Server errors are retried with a growing wait.
The importer only uses ``get()``, ``paginate()`` and ``download()``; the
tests give it a fake client with the same three methods.
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


def urllib_transport(url, headers):
    """One request, redirects not followed (downloads redirect to a URL
    which must not get our token)"""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=60) as response:
            return Response(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
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

    def _wait_for_slot(self):
        now = self.clock()
        while self._sent and self._sent[0] <= now - WINDOW:
            self._sent.popleft()
        if len(self._sent) >= LIMIT:
            self.sleep(self._sent[0] + WINDOW - now)
        self._sent.append(self.clock())

    def _request(self, url, *, auth=True):
        headers = {"User-Agent": USER_AGENT}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(RETRIES):
            self._wait_for_slot()
            response = self.transport(url, headers)
            if response.status == 429:
                wait = int(_header(response, "Retry-After") or WINDOW)
                self.sleep(wait)
                continue
            if response.status >= 500:
                self.sleep(2**attempt)
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

    def download(self, url):
        """The file's bytes: the API redirects to a short-lived URL, which
        doesn't get the token"""
        response = self._request(url)
        if response.status in {301, 302, 303, 307, 308}:
            response = self._request(_header(response, "Location"), auth=False)
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
