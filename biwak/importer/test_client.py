import json

from django.test import SimpleTestCase

from biwak.importer import client as api
from biwak.importer.client import BasecampClient, Response


class Transport:
    """Answers from a list, remembering the requests"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.methods = []

    def __call__(self, url, headers, method="GET"):
        self.requests.append((url, headers))
        self.methods.append(method)
        return self.responses.pop(0)


def ok(data, **headers):
    return Response(200, headers, json.dumps(data).encode())


class ClientCase(SimpleTestCase):
    def make(self, *responses):
        self.transport = Transport(*responses)
        self.slept = []
        self.now = 0.0

        def sleep(seconds):
            self.slept.append(seconds)
            self.now += seconds

        return BasecampClient(
            "1000",
            "secret",
            transport=self.transport,
            sleep=sleep,
            clock=lambda: self.now,
        )


class ClientTest(ClientCase):
    def test_get_sends_the_token_and_a_user_agent(self):
        client = self.make(ok({"id": 1}))
        self.assertEqual(client.get("/projects/1.json"), {"id": 1})
        url, headers = self.transport.requests[0]
        self.assertEqual(url, "https://3.basecampapi.com/1000/projects/1.json")
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertIn("Biwak", headers["User-Agent"])

    def test_parameters(self):
        client = self.make(ok([]))
        list(client.paginate("/x.json", status="archived"))
        self.assertEqual(
            self.transport.requests[0][0],
            "https://3.basecampapi.com/1000/x.json?status=archived",
        )

    def test_pagination_follows_the_link_header(self):
        next_url = "https://3.basecampapi.com/1000/x.json?page=2"
        client = self.make(ok([1, 2], Link=f'<{next_url}>; rel="next"'), ok([3]))
        self.assertEqual(list(client.paginate("/x.json")), [1, 2, 3])
        self.assertEqual(self.transport.requests[1][0], next_url)

    def test_429_waits_as_told(self):
        client = self.make(Response(429, {"Retry-After": "7"}), ok({"id": 1}))
        self.assertEqual(client.get("/x.json"), {"id": 1})
        self.assertEqual(self.slept, [7])

    def test_a_redirect_is_closed(self):
        """urllib raises the download's redirect as an error: closed after
        reading, else Python warns about each file (ResourceWarning)"""
        import email.message
        import io
        import urllib.error
        from unittest import mock

        body = io.BytesIO(b"")
        headers = email.message.Message()
        headers["Location"] = "https://storage.example.org/blob"
        error = urllib.error.HTTPError("https://x", 302, "Found", headers, body)
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch("urllib.request.build_opener", return_value=opener):
            response = api.urllib_transport("https://x", {})
        self.assertEqual(response.status, 302)
        self.assertTrue(body.closed)

    def test_waits_are_told(self):
        """For the command's progress: who waits how long and why"""
        client = self.make(Response(429, {"Retry-After": "7"}), ok({"id": 1}))
        told = []
        client.on_wait = lambda seconds, why: told.append((seconds, why))
        client.get("/x.json")
        self.assertEqual(told, [(7, "Basecamp asked to wait (429)")])
        self.assertEqual(client.request_count, 2)

    def test_server_errors_are_retried(self):
        client = self.make(Response(503), Response(502), ok({"id": 1}))
        self.assertEqual(client.get("/x.json"), {"id": 1})
        self.assertEqual(self.slept, [1, 2])

    def test_gives_up_after_the_retries(self):
        client = self.make(*[Response(500)] * api.RETRIES)
        with self.assertRaises(api.ApiError):
            client.get("/x.json")

    def test_404_is_not_found(self):
        client = self.make(Response(404))
        with self.assertRaises(api.NotFound):
            client.get("/x.json")

    def test_at_most_50_requests_per_10_seconds(self):
        client = self.make(*[ok({})] * 52)
        for _ in range(51):
            client.get("/x.json")
        # The 51st waits until the first one is 10 seconds old
        self.assertEqual(self.slept, [10.0])
        client.get("/x.json")
        self.assertEqual(self.slept, [10.0])

    def test_download_follows_the_redirect_without_the_token(self):
        client = self.make(
            Response(302, {"Location": "https://storage.example.org/blob?sig=1"}),
            Response(200, {}, b"file"),
        )
        self.assertEqual(
            client.download("https://3.basecampapi.com/x/download/a.png"), b"file"
        )
        first, second = self.transport.requests
        self.assertIn("Authorization", first[1])
        self.assertEqual(second[0], "https://storage.example.org/blob?sig=1")
        self.assertNotIn("Authorization", second[1])

    def test_download_of_a_missing_file(self):
        client = self.make(Response(404))
        with self.assertRaises(api.NotFound):
            client.download("https://3.basecampapi.com/x/download/a.png")

    def test_archive_project(self):
        client = self.make(Response(204))
        client.archive_project(42)
        self.assertEqual(
            self.transport.requests[0][0],
            "https://3.basecampapi.com/1000/projects/42/status/archived.json",
        )
        self.assertEqual(self.transport.methods, ["PUT"])
        self.assertIn("Authorization", self.transport.requests[0][1])

    def test_archive_project_not_allowed(self):
        client = self.make(Response(403))
        with self.assertRaisesMessage(api.ApiError, "not allowed"):
            client.archive_project(42)


STORAGE = "https://storage.example.org/blob-1"
FILE_URL = "https://3.basecampapi.com/1000/buckets/1/uploads/2/download/a.pdf"


def redirect(location):
    return Response(302, {"Location": location})


class CacheTest(ClientCase):
    """Downloads by the storage location the API redirects to"""

    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = api.FileCache(tmp.name)
        self.directory = tmp.name

    def make(self, *responses):
        client = super().make(*responses)
        client.cache = self.cache
        return client

    def files(self):
        import os

        return sorted(
            name for _root, _dirs, names in os.walk(self.directory) for name in names
        )

    def test_a_miss_downloads_and_stores_a_hit_skips_the_storage(self):
        client = self.make(
            redirect(f"{STORAGE}?sig=1"),
            Response(200, {}, b"file"),
            redirect(f"{STORAGE}?sig=2"),
        )
        self.assertEqual(client.download(FILE_URL), b"file")
        self.assertEqual(len(self.files()), 1)
        # Another signature, the same location: from the cache, only the
        # API's request
        self.assertEqual(client.download(FILE_URL), b"file")
        self.assertEqual(len(self.transport.requests), 3)
        self.assertEqual(client.file_counts, {"downloaded": 1, "cached": 1})

    def test_a_new_location_downloads_again(self):
        """A replaced upload: the same API URL, a new storage location"""
        client = self.make(
            redirect(f"{STORAGE}?sig=1"),
            Response(200, {}, b"version 1"),
            redirect("https://storage.example.org/blob-2?sig=1"),
            Response(200, {}, b"version 2"),
        )
        self.assertEqual(client.download(FILE_URL), b"version 1")
        self.assertEqual(client.download(FILE_URL), b"version 2")
        self.assertEqual(client.file_counts, {"downloaded": 2})

    def test_without_a_cache(self):
        client = self.make(
            redirect(STORAGE),
            Response(200, {}, b"file"),
            redirect(STORAGE),
            Response(200, {}, b"file"),
        )
        client.cache = None
        client.download(FILE_URL)
        client.download(FILE_URL)
        self.assertEqual(client.file_counts, {"downloaded": 2})
        self.assertEqual(self.files(), [])

    def test_a_failing_download_is_not_cached(self):
        client = self.make(redirect(STORAGE), Response(403, {}, b"denied"))
        with self.assertRaises(api.ApiError):
            client.download(FILE_URL)
        self.assertEqual(self.files(), [])
        self.assertEqual(client.file_counts, {})

    def test_an_answer_without_a_redirect_is_not_cached(self):
        client = self.make(Response(200, {}, b"file"))
        self.assertEqual(client.download(FILE_URL), b"file")
        self.assertEqual(self.files(), [])
        self.assertEqual(client.file_counts, {"downloaded": 1, "not redirected": 1})

    def test_profile_images_are_not_cached_nor_counted(self):
        client = self.make(redirect(STORAGE), Response(200, {}, b"image"))
        client.download(FILE_URL, cache=False)
        self.assertEqual(self.files(), [])
        self.assertEqual(client.file_counts, {})

    def test_an_interrupted_write_leaves_nothing(self):
        from unittest import mock

        with (
            mock.patch("os.replace", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.cache.put(STORAGE, b"file")
        self.assertEqual(self.files(), [])
        self.assertIsNone(self.cache.get(STORAGE))

    def test_the_key_leaves_out_the_query(self):
        self.assertEqual(api.storage_key(f"{STORAGE}?sig=1&exp=2"), STORAGE)

    def test_default_directory(self):
        from pathlib import Path
        from unittest import mock

        with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "/srv/cache"}):
            self.assertEqual(api.default_cache_dir(), Path("/srv/cache/biwak/basecamp"))
        with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": ""}):
            self.assertEqual(
                api.default_cache_dir(), Path.home() / ".cache/biwak/basecamp"
            )


class AnswerCacheTest(ClientCase):
    """The API's JSON answers, reused while fresh"""

    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = tmp.name
        self.wall = 1_000_000.0
        self.answers = api.AnswerCache(tmp.name, 3600, clock=lambda: self.wall)

    def make(self, *responses, token="secret"):
        client = super().make(*responses)
        client.token = token
        client.answers = self.answers
        return client

    def test_a_second_client_reads_the_answers_from_the_cache(self):
        """A dry run and the run after it: Basecamp is asked once"""
        self.make(ok({"id": 1})).get("/projects/1.json")
        client = self.make()
        self.assertEqual(client.get("/projects/1.json"), {"id": 1})
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(client.answer_counts, {"cached": 1})
        self.assertEqual(client.request_count, 0)

    def test_pages_keep_their_link(self):
        next_url = "https://3.basecampapi.com/1000/x.json?page=2"
        first = self.make(ok([1, 2], Link=f'<{next_url}>; rel="next"'), ok([3]))
        self.assertEqual(list(first.paginate("/x.json")), [1, 2, 3])
        client = self.make()
        self.assertEqual(list(client.paginate("/x.json")), [1, 2, 3])
        self.assertEqual(client.answer_counts, {"cached": 2})

    def test_an_old_answer_is_fetched_again(self):
        self.make(ok({"v": 1})).get("/x.json")
        self.wall += 3601
        client = self.make(ok({"v": 2}))
        self.assertEqual(client.get("/x.json"), {"v": 2})
        self.assertEqual(client.answer_counts, {})
        # and stored again
        self.assertEqual(self.make().get("/x.json"), {"v": 2})

    def test_another_token_asks_again(self):
        """Who asks decides what the answer contains (addresses)"""
        self.make(ok({"email_address": None}), token="member").get("/people.json")
        client = self.make(ok({"email_address": "a@example.org"}), token="admin")
        self.assertEqual(client.get("/people.json"), {"email_address": "a@example.org"})
        self.assertEqual(client.answer_counts, {})

    def test_the_token_is_not_stored(self):
        import os

        self.make(ok({"id": 1})).get("/x.json")
        for root, _dirs, names in os.walk(self.directory):
            for name in names:
                with open(os.path.join(root, name), "rb") as file:
                    self.assertNotIn(b"secret", file.read())

    def test_errors_are_not_cached(self):
        client = self.make(Response(404, {}, b""), ok({"id": 1}))
        with self.assertRaises(api.NotFound):
            client.get("/x.json")
        self.assertEqual(client.get("/x.json"), {"id": 1})

    def test_a_broken_file_is_a_miss(self):
        self.make(ok({"id": 1})).get("/x.json")
        self.answers._path(
            "secret", "https://3.basecampapi.com/1000/x.json"
        ).write_text("{")
        client = self.make(ok({"id": 2}))
        self.assertEqual(client.get("/x.json"), {"id": 2})

    def test_make_client(self):
        import tempfile
        from pathlib import Path

        from biwak.importer.management.commands.import_basecamp import make_client

        with tempfile.TemporaryDirectory() as directory:
            client = make_client(
                "1000", "secret", cache_dir=directory, answers_max_age=60
            )
            self.assertEqual(client.answers.directory, Path(directory) / "answers")
            self.assertEqual(client.answers.max_age, 60)
            client = make_client("1000", "secret", cache_dir=directory)
            self.assertIsNone(client.answers)
        client = make_client("1000", "secret", answers_max_age=60)
        self.assertIsNone(client.answers)
        self.assertIsNone(client.cache)
