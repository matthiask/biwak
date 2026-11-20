from urllib.parse import urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.files.test_attachments import PNG, Fixture
from biwak.test_utils import project


class APITest(Fixture, TestCase):
    def api(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="Test", access=access)
        return {"authorization": f"Bearer {secret}"}

    def post_file(self, headers, name="sketch.png", content=PNG):
        return self.client.post(
            f"/api/v1/projects/{self.project.pk}/attachments/",
            {"file": SimpleUploadedFile(name, content)},
            headers=headers,
        )

    def test_upload_link_and_download(self):
        headers = self.api(self.ada)
        response = self.post_file(headers)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["markdown"], f"![sketch.png](attachment:{data['key']})")
        self.assertIsNone(data["item_id"])
        self.assertEqual(
            data["url"], f"http://127.0.0.1:8000/attachments/{data['key']}/sketch.png"
        )

        response = self.client.patch(
            f"/api/v1/todos/{self.secret.pk}/",
            {"notes": data["markdown"]},
            content_type="application/json",
            headers=headers,
        )
        self.assertIn(
            f'<img src="http://127.0.0.1:8000/attachments/{data["key"]}/sketch.png"',
            response.json()["notes_html"],
        )
        response = self.client.get(
            f"/api/v1/attachments/{data['key']}/", headers=headers
        )
        self.assertEqual(response.json()["item_id"], self.secret.pk)
        download = urlsplit(response.json()["download_url"]).path
        self.assertEqual(download, f"/api/v1/attachments/{data['key']}/download/")
        response = self.client.get(download, headers=headers)
        self.assertEqual(b"".join(response.streaming_content), PNG)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

        # A client gets 404 for the internal to-do's attachment, by key too
        client = self.api(self.cleo)
        for path in [f"attachments/{data['key']}/", download.removeprefix("/api/v1/")]:
            with self.subTest(path=path):
                response = self.client.get(f"/api/v1/{path}", headers=client)
                self.assertEqual(response.status_code, 404)

    def test_client_and_read_only(self):
        response = self.post_file(self.api(self.cleo))
        self.assertEqual(response.status_code, 201)
        response = self.post_file(self.api(self.ada, access="read"))
        self.assertEqual(response.status_code, 403)
        other = project("Other", members=[self.ada])
        response = self.client.post(
            f"/api/v1/projects/{other.pk}/attachments/",
            {"file": SimpleUploadedFile("x.png", PNG)},
            headers=self.api(self.cleo),
        )
        self.assertEqual(response.status_code, 404)
