import json

from django.test import SimpleTestCase

from biwak.importer import client as api
from biwak.importer.client import BasecampClient, Response


class Transport:
    """Answers from a list, remembering the requests"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, headers):
        self.requests.append((url, headers))
        return self.responses.pop(0)


def ok(data, **headers):
    return Response(200, headers, json.dumps(data).encode())


class ClientTest(SimpleTestCase):
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
