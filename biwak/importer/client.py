"""The Basecamp API (specs/import-basecamp.md): OAuth bearer token, flat
routes, pagination by ``Link`` headers, rate limits.

Basecamp answers 429 with ``Retry-After``: wait as told. Otherwise at most
50 requests per 10 seconds. Server errors are retried with a growing wait.
A 401 (an expired token) asks ``renew_token`` for a new one and tries
again, or stops the run (``Unauthorized``).
The importer uses ``get()``, ``paginate()`` and ``download()``, and
``archive_project()`` with ``--archive``; the tests give it a fake client
with the same methods.

Downloads go through a cache on disk (``FileCache``), keyed by where the
API redirects to: an upload's download URL stays the same when a new
version replaces its file, the storage location doesn't (verified
2026-11-22). The API's JSON answers go through ``AnswerCache``, reused
for an hour, so a dry run and the run after it read Basecamp once.
"""

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path


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


class Unauthorized(Exception):
    """401: the token expired or was revoked. Not an ``ApiError``, which
    the importer reports and goes on with: without a token nothing more
    can be read, so the run stops."""


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


def default_cache_dir():
    """``$XDG_CACHE_HOME/biwak/basecamp``, ``~/.cache`` without it"""
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "biwak" / "basecamp"


class FileCache:
    """Downloaded files on disk, by the storage location they came from
    (without the query, the signed short-lived part). Never cleaned up:
    a location's bytes don't change. Written to a temporary file next to
    the final one and renamed, so an interrupted write leaves nothing."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, key):
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.directory / digest[:2] / digest

    def get(self, key):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key, data):
        _write(self._path(key), data)


class AnswerCache:
    """The API's JSON answers on disk, by who asks and URL, reused while
    younger than ``max_age`` seconds: a dry run and the run after it
    read Basecamp once. Who asks is part of the key because what an
    answer contains depends on it (addresses only for administrators):
    the person once known (``BasecampClient.identify()``), else the
    token; only the key's hash is stored. An older answer is fetched
    again and overwritten; none is ever deleted."""

    def __init__(self, directory, max_age, *, clock=time.time):
        self.directory = Path(directory)
        self.max_age = max_age
        self.clock = clock

    def _path(self, identity, url):
        digest = hashlib.sha256(f"{identity}\n{url}".encode()).hexdigest()
        return self.directory / digest[:2] / digest

    def get(self, identity, url, *, newer_than=None):
        """``(body, link)``, None without a fresh answer, or one fetched
        before ``newer_than`` (a datetime)"""
        try:
            stored = json.loads(self._path(identity, url).read_bytes())
        except FileNotFoundError, ValueError:
            return None
        if self.clock() - stored["fetched"] > self.max_age:
            return None
        if newer_than is not None and stored["fetched"] < newer_than.timestamp():
            return None
        return stored["body"].encode(), stored["link"]

    def put(self, identity, url, body, link):
        stored = {"fetched": self.clock(), "link": link, "body": body.decode()}
        _write(self._path(identity, url), json.dumps(stored).encode())


def _write(path, data):
    """Written to a temporary file next to ``path`` and renamed, so an
    interrupted write leaves nothing"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def storage_key(location):
    """The storage location without its query string"""
    parts = urllib.parse.urlsplit(location)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class BasecampClient:
    def __init__(
        self,
        account,
        token,
        *,
        cache=None,
        answers=None,
        renew_token=None,
        transport=urllib_transport,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        """``cache``: a ``FileCache`` for downloads, ``answers`` an
        ``AnswerCache`` for the JSON answers, either None for none.
        ``renew_token``: called for a new token when Basecamp answers 401
        (OAuth tokens of the Basecamp CLI last an hour), None to stop"""
        self.account = account
        self.token = token
        self.renew_token = renew_token
        # The person, once ``identify()`` knows them
        self.person_id = None
        self.cache = cache
        self.answers = answers
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        # For the report: files "downloaded", "cached" (from the cache),
        # "not redirected" (the API answered with the file itself: not
        # cached, also counted as downloaded)
        self.file_counts = Counter()
        # JSON answers "cached" (from the ``AnswerCache``)
        self.answer_counts = Counter()
        self._sent = deque()
        # For progress: requests sent, and who to tell about a wait
        # (``on_wait(seconds, why)``)
        self.request_count = 0
        self.on_wait = None
        self.on_renew = None

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
        renewed = False
        for attempt in range(RETRIES):
            if auth:
                headers["Authorization"] = f"Bearer {self.token}"
            self._wait_for_slot()
            response = self.transport(url, headers, method=method)
            if response.status == 401 and auth:
                if renewed or not self._renew():
                    raise Unauthorized(url)
                renewed = True
                continue
            if response.status == 429:
                wait = int(_header(response, "Retry-After") or WINDOW)
                self._sleep(wait, "Basecamp asked to wait (429)")
                continue
            if response.status >= 500:
                self._sleep(2**attempt, f"server error {response.status}, retrying")
                continue
            return response
        raise ApiError(f"Giving up on {url}: status {response.status}")

    def _renew(self):
        """Whether ``renew_token`` gave a token other than the one refused"""
        if self.renew_token is None:
            return False
        token = self.renew_token()
        if not token or token == self.token:
            return False
        self.token = token
        if self.on_renew is not None:
            self.on_renew()
        return True

    def identify(self):
        """The token owner's profile (asked, never from the cache); from
        now on the cached answers are theirs, whatever the token"""
        response = self._json(self._url("/my/profile.json", None))
        profile = json.loads(response.body)
        self.person_id = profile["id"]
        return profile

    @property
    def identity(self):
        """Whose answers the ``AnswerCache`` holds: the person once known,
        so a renewed token still finds them, else the token"""
        return f"person {self.person_id}" if self.person_id else self.token

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

    def _answer(self, url, newer_than=None):
        """``(body, link)`` of a JSON answer, from the ``AnswerCache``
        while fresh and not fetched before ``newer_than``"""
        if (
            self.answers is not None
            and (cached := self.answers.get(self.identity, url, newer_than=newer_than))
            is not None
        ):
            self.answer_counts["cached"] += 1
            return cached
        response = self._json(url)
        link = _header(response, "Link") or ""
        if self.answers is not None:
            self.answers.put(self.identity, url, response.body, link)
        return response.body, link

    def get(self, path, **params):
        return json.loads(self._answer(self._url(path, params))[0])

    def paginate(self, path, *, newer_than=None, **params):
        """All items of a collection, following the ``Link: rel="next"``.
        ``newer_than``: a cached answer fetched before isn't used (what the
        importer knows changed since, found 2026-11-28)."""
        url = self._url(path, params)
        while url:
            body, link = self._answer(url, newer_than)
            yield from json.loads(body)
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

    def download(self, url, *, accept=None, cache=True):
        """The file's bytes: the API redirects to a short-lived URL, which
        doesn't get the token. ``accept`` is the ``Accept`` header. With
        ``cache`` (and a ``FileCache``), the redirect's storage location
        is looked up first and stored after; profile images pass False
        (their URL is the person's, counted nowhere)."""
        response = self._request(url, accept=accept)
        key = None
        if response.status in {301, 302, 303, 307, 308}:
            location = _header(response, "Location")
            if cache and self.cache is not None:
                key = storage_key(location)
                if (data := self.cache.get(key)) is not None:
                    self.file_counts["cached"] += 1
                    return data
            response = self._request(location, auth=False, accept=accept)
        elif cache and response.status == 200:
            self.file_counts["not redirected"] += 1
        if response.status == 404:
            raise NotFound(url)
        if response.status != 200:
            raise ApiError(f"{url}: status {response.status}")
        if key is not None:
            self.cache.put(key, response.body)
        if cache:
            self.file_counts["downloaded"] += 1
        return response.body


def _header(response, name):
    for key, value in response.headers.items():
        if key.lower() == name.lower():
            return value
    return None
