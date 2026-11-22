import datetime as dt
import io
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import boto3
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from moto import mock_aws

from biwak.accounts.models import APIToken
from biwak.files import attachments
from biwak.files.models import MAX_SIZE, Attachment
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.templatetags.biwak import markdown, render_markdown
from biwak.test_utils import person, project


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00"
    b"\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def upload(project, user, name="sketch.png", content=PNG):
    return attachments.upload(
        project=project, file=ContentFile(content, name=name), uploaded_by=user
    )


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )

    def status(self, url, **kwargs):
        """The status of a GET; reading the file closes it (the test
        client's wrapper)"""
        response = self.client.get(url, **kwargs)
        if response.streaming:
            b"".join(response.streaming_content)
        return response.status_code

    def visible(self, user, attachment):
        return Attachment.objects.visible_to(user).filter(pk=attachment.pk).exists()


class OperationsTest(Fixture, TestCase):
    def test_upload(self):
        attachment = upload(self.project, self.ada, name="../dir\\My  sketch.png")
        self.assertEqual(attachment.name, "My sketch.png")
        self.assertEqual(attachment.content_type, "image/png")
        self.assertEqual(attachment.size, len(PNG))
        self.assertEqual(len(attachment.key), 16)
        self.assertTrue(
            attachment.file.name.startswith(
                f"files/{self.project.pk}/{attachment.key}/"
            )
        )
        with attachment.file.open("rb") as file:
            self.assertEqual(file.read(), PNG)
        self.assertEqual(
            attachment.markdown, f"![My sketch.png](attachment:{attachment.key})"
        )
        self.assertIsNone(attachment.item)

        pdf = upload(self.project, self.ada, name="Plan [v2].pdf", content=b"%PDF")
        self.assertEqual(pdf.content_type, "application/pdf")
        self.assertEqual(pdf.markdown, rf"[Plan \[v2\].pdf](attachment:{pdf.key})")
        # The name decides the type, not what the browser claims
        self.assertEqual(
            upload(self.project, self.ada, name="x", content=b"<html>").content_type,
            "application/octet-stream",
        )

    def test_size_limit(self):
        file = ContentFile(b"x", name="big.bin")
        file.size = MAX_SIZE + 1
        with self.assertRaises(attachments.UploadError):
            attachments.upload(project=self.project, file=file, uploaded_by=self.ada)
        self.assertFalse(Attachment.objects.exists())

    def test_linking_when_texts_are_saved(self):
        a, b, c = (upload(self.project, self.ada) for _i in range(3))
        todo = ops.create_todo(
            todolist=self.internal,
            title="With a sketch",
            creator=self.ada,
            notes=f"See {a.markdown}",
        )
        a.refresh_from_db()
        self.assertEqual(a.item, todo)

        ops.update_todo(self.todo, actor=self.ada, notes=f"[b](attachment:{b.key})")
        b.refresh_from_db()
        self.assertEqual(b.item, self.todo)
        # Linked once, it stays with its item
        ops.update_todo(todo, actor=self.ada, notes=b.markdown)
        b.refresh_from_db()
        self.assertEqual(b.item, self.todo)

        ops.add_comment(self.secret, author=self.ada, content=c.markdown)
        c.refresh_from_db()
        self.assertEqual(c.item, self.secret)

        message = ops.create_message(
            project=self.project,
            title="News",
            creator=self.ada,
            content=upload(self.project, self.ada).markdown,
        )
        self.assertEqual(message.attachments.count(), 1)

    def test_linking_only_own_uploads_in_the_project(self):
        other = project("Other", members=[self.ada])
        elsewhere = upload(other, self.ada)
        bobs = upload(self.project, self.bob)
        ops.add_comment(
            self.todo,
            author=self.ada,
            content=f"{elsewhere.markdown} {bobs.markdown}",
        )
        self.assertFalse(Attachment.objects.filter(item__isnull=False).exists())

    def test_visibility(self):
        """Through the item, unlinked ones only for their uploader"""
        unlinked = upload(self.project, self.ada)
        self.assertTrue(self.visible(self.ada, unlinked))
        self.assertFalse(self.visible(self.bob, unlinked))
        self.assertFalse(self.visible(self.cleo, unlinked))

        secret = upload(self.project, self.ada)
        ops.update_todo(self.secret, actor=self.ada, notes=secret.markdown)
        shared = upload(self.project, self.ada)
        ops.add_comment(self.todo, author=self.ada, content=shared.markdown)
        for user, attachment, expected in [
            (self.ada, secret, True),
            (self.bob, secret, True),
            (self.cleo, secret, False),
            (self.cleo, shared, True),
        ]:
            with self.subTest(user=user, attachment=attachment):
                self.assertEqual(self.visible(user, attachment), expected)

        # Follows the item when it moves and when the switch changes
        ops.move_todo(self.todo, todolist=self.internal, actor=self.ada)
        self.assertFalse(self.visible(self.cleo, shared))
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        self.assertTrue(self.visible(self.cleo, secret))
        self.assertTrue(self.visible(self.cleo, shared))
        # Trashed items' attachments are gone with them
        ops.trash(self.secret, actor=self.ada)
        self.assertFalse(self.visible(self.ada, secret))

        # Not in limited projects people can't open
        limited = project("Limited", all_access=False, members=[self.ada])
        own = upload(limited, self.bob)
        self.assertFalse(self.visible(self.bob, own))

    def test_delete_unlinked_and_purge(self):
        old = upload(self.project, self.ada)
        recent = upload(self.project, self.ada)
        linked = upload(self.project, self.ada)
        ops.update_todo(self.secret, actor=self.ada, notes=linked.markdown)
        Attachment.objects.filter(pk__in=[old.pk, linked.pk]).update(
            created_at=timezone.now() - dt.timedelta(days=2)
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(attachments.delete_unlinked(), 1)
        self.assertFalse(default_storage.exists(old.file.name))
        self.assertTrue(default_storage.exists(recent.file.name))
        self.assertEqual(
            set(Attachment.objects.values_list("pk", flat=True)),
            {recent.pk, linked.pk},
        )

        # Deleting the item for good deletes its attachments' files
        ops.trash(self.internal, actor=self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            ops.purge_trash(now=timezone.now() + dt.timedelta(days=31))
        self.assertFalse(Item.objects.filter(pk=self.secret.pk).exists())
        self.assertFalse(Attachment.objects.filter(pk=linked.pk).exists())
        self.assertFalse(default_storage.exists(linked.file.name))

    def test_fairy_tasks(self):
        old = upload(self.project, self.ada)
        Attachment.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - dt.timedelta(days=2)
        )
        with self.captureOnCommitCallbacks(execute=True):
            call_command("fairy_tasks", stdout=io.StringIO())
        self.assertFalse(Attachment.objects.exists())
        self.assertFalse(default_storage.exists(old.file.name))

    def test_markdown(self):
        image = upload(self.project, self.ada)
        pdf = upload(self.project, self.ada, name="plan.pdf", content=b"%PDF")
        notes = (
            f"{image.markdown}\n\n{pdf.markdown}\n\n"
            "[gone](attachment:aaaaaaaaaaaaaaaa) [web](https://example.org)"
        )
        ops.update_todo(self.todo, actor=self.ada, notes=notes)
        html = str(markdown(notes, self.todo))
        # Pages: the storage's URL (on disk MEDIA_URL; specs/files.md)
        self.assertIn(
            f'<img src="{image.file.url}" alt="sketch.png"'
            ' class="wb-attachment-image" loading="lazy"',
            html,
        )
        self.assertIn(f'<a href="{pdf.file.url}">plan.pdf</a>', html)
        self.assertIn("<p>attachment <a", html)  # gone
        self.assertIn(
            '<a href="https://example.org" target="_blank" rel="noopener noreferrer">'
            "web</a>",
            html,
        )
        self.assertIn(
            f'src="http://127.0.0.1:8000/attachments/{image.key}/',
            str(render_markdown(image.markdown, self.todo, absolute=True)),
        )


class ForeignReferencesTest(Fixture, TestCase):
    """A reference to an attachment of another item (copied from an
    internal to-do into a visible one) shows neither its name nor its URL,
    which has the name: a plain "attachment" (specs/files.md)"""

    def setUp(self):
        super().setUp()
        self.salaries = upload(self.project, self.ada, name="Salaries 2027.pdf")
        ops.update_todo(self.secret, actor=self.ada, notes=self.salaries.markdown)
        self.own = upload(self.project, self.ada, name="sketch.png")
        ops.update_todo(
            self.todo,
            actor=self.ada,
            notes=f"{self.own.markdown} [the table](attachment:{self.salaries.key})"
            f" ![chart](attachment:{self.salaries.key})",
        )

    def test_rendering(self):
        html = str(markdown(self.todo.todo.notes, self.todo))
        self.assertIn(self.own.file.url, html)
        self.assertNotIn("Salaries", html)
        self.assertNotIn(self.salaries.key, html)
        self.assertNotIn("the table", html)
        self.assertIn(' loading="lazy" /> attachment attachment</p>', html)
        # Still linked where it belongs
        html = str(markdown(self.secret.todo.notes, self.secret))
        self.assertIn(self.salaries.file.url, html)

    def test_page_and_api(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(response, self.own.file.url)
        # (The key is in the to-do's form, without the name)
        self.assertNotContains(response, "Salaries")
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        data = self.client.get(
            f"/api/v1/todos/{self.todo.pk}/",
            headers={"authorization": f"Bearer {secret}"},
        ).json()
        self.assertIn(f"/attachments/{self.own.key}/sketch.png", data["notes_html"])
        self.assertNotIn("Salaries", data["notes_html"])
        self.assertNotIn(self.salaries.key, data["notes_html"])


class ViewsTest(Fixture, TestCase):
    def post_file(self, name="sketch.png", content=PNG, project=None):
        return self.client.post(
            f"/projects/{(project or self.project).pk}/attachments/",
            {"file": SimpleUploadedFile(name, content)},
        )

    def test_upload_and_download(self):
        self.client.force_login(self.ada)
        response = self.post_file()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["markdown"], f"![sketch.png](attachment:{data['key']})")
        self.assertEqual(data["url"], f"/attachments/{data['key']}/sketch.png")
        self.assertEqual(self.client.post("/projects/1/attachments/x").status_code, 404)
        self.assertEqual(
            self.client.post(f"/projects/{self.project.pk}/attachments/").status_code,
            400,
        )

        response = self.client.get(data["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PNG)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response["Content-Disposition"].startswith("inline"))
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        # The name in the URL is only for people
        self.assertEqual(self.status(f"/attachments/{data['key']}/other.png"), 200)

        # Saving the to-do links it, and the to-do page shows it
        response = self.client.post(
            self.secret.get_absolute_url(),
            {"form": "todo", "title": "Secret", "notes": data["markdown"]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attachment.objects.get().item_id, self.secret.pk)
        response = self.client.get(self.secret.get_absolute_url())
        stored = Attachment.objects.get().file.url
        self.assertContains(response, f'<img src="{stored}"')
        self.assertContains(response, "data-attachments=")
        self.assertContains(response, "Attach files")

        # Bob sees the to-do, so he sees the attachment too
        self.client.force_login(self.bob)
        self.assertEqual(self.status(data["url"]), 200)

    def test_client(self):
        self.client.force_login(self.cleo)
        response = self.post_file(name="from-cleo.png")
        self.assertEqual(response.status_code, 201)
        key = response.json()["key"]
        response = self.client.post(
            self.todo.get_absolute_url(),
            {"form": "comment", "content": f"Here: ![x](attachment:{key})"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attachment.objects.get(key=key).item_id, self.todo.pk)
        self.assertEqual(self.status(f"/attachments/{key}/x"), 200)

        # An attachment of an internal to-do: 404, also by its key
        secret = upload(self.project, self.ada)
        ops.update_todo(self.secret, actor=self.ada, notes=secret.markdown)
        self.assertEqual(self.status(secret.get_absolute_url()), 404)
        # Somebody else's unlinked upload: 404
        unlinked = upload(self.project, self.ada)
        self.assertEqual(self.status(unlinked.get_absolute_url()), 404)
        # Moving the to-do into the internal list hides its attachments
        ops.move_todo(self.todo, todolist=self.internal, actor=self.ada)
        self.assertEqual(self.status(f"/attachments/{key}/x"), 404)
        # Not into projects the client isn't a member of
        other = project("Other", members=[self.ada])
        self.assertEqual(self.post_file(project=other).status_code, 404)

    def test_dangerous_types_are_downloads(self):
        self.client.force_login(self.ada)
        for name, content, inline in [
            ("evil.svg", b"<svg onload='alert(1)'/>", False),
            ("evil.html", b"<script>alert(1)</script>", False),
            ("notes.txt", b"hello", False),
            ("plan.pdf", b"%PDF", True),
        ]:
            with self.subTest(name=name):
                url = self.post_file(name=name, content=content).json()["url"]
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                disposition = response["Content-Disposition"]
                self.assertEqual(disposition.startswith("inline"), inline)
                self.assertEqual(disposition.startswith("attachment"), not inline)
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                b"".join(response.streaming_content)

    def test_too_large(self):
        self.client.force_login(self.ada)
        with patch.object(attachments, "MAX_SIZE", 3):
            response = self.post_file()
        self.assertEqual(response.status_code, 413)
        self.assertIn("at most", response.json()["detail"])
        self.assertFalse(Attachment.objects.exists())

    def test_inline_add_form(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(
            response, f'data-attachments="/projects/{self.project.pk}/attachments/"'
        )


@mock_aws
@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": "biwak-test",
                "access_key": "testing",
                "secret_key": "testing",
                "region_name": "us-east-1",
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
                "signature_version": "s3v4",
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class BucketTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="biwak-test")

    def test_presigned_redirect(self):
        attachment = upload(self.project, self.ada, name="evil.svg", content=b"<svg/>")
        objects = boto3.client("s3", region_name="us-east-1").list_objects_v2(
            Bucket="biwak-test"
        )
        self.assertEqual(
            [o["Key"] for o in objects["Contents"]], [attachment.file.name]
        )
        ops.update_todo(self.secret, actor=self.ada, notes=attachment.markdown)

        self.client.force_login(self.ada)
        response = self.client.get(attachment.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        url = urlsplit(response["Location"])
        self.assertIn("biwak-test", url.netloc + url.path)
        query = parse_qs(url.query)
        self.assertEqual(query["X-Amz-Expires"], ["3600"])
        self.assertEqual(query["response-content-type"], ["image/svg+xml"])
        self.assertEqual(
            query["response-content-disposition"], ['attachment; filename="evil.svg"']
        )

        self.client.force_login(self.cleo)
        self.assertEqual(self.status(attachment.get_absolute_url()), 404)

        # Purging deletes the object in the bucket
        ops.trash(self.secret, actor=self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            ops.purge_trash(now=timezone.now() + dt.timedelta(days=31))
        objects = boto3.client("s3", region_name="us-east-1").list_objects_v2(
            Bucket="biwak-test"
        )
        self.assertNotIn("Contents", objects)


def stored_files(project):
    """Every file stored for the project"""
    found = []
    todo = [f"files/{project.pk}"]
    while todo:
        folder = todo.pop()
        try:
            folders, files = default_storage.listdir(folder)
        except FileNotFoundError:
            continue
        todo += [f"{folder}/{f}" for f in folders]
        found += [f"{folder}/{f}" for f in files]
    return found


class StorageNameTest(Fixture, TestCase):
    def test_a_long_name_with_umlauts_is_stored(self):
        name = "ä" * 200 + ".txt"
        attachment = upload(self.project, self.ada, name=name, content=b"x")
        self.assertEqual(attachment.name, name)
        self.assertTrue(attachment.file.name.endswith(".txt"))
        self.assertLessEqual(len(attachment.file.name.rsplit("/", 1)[1].encode()), 255)

    def test_a_long_name_of_a_file_version_is_stored(self):
        item = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="ä" * 200 + ".txt"),
            creator=self.ada,
        )
        version = item.upload.versions.get()
        self.assertEqual(version.name, "ä" * 200 + ".txt")
        self.assertTrue(version.file.name.endswith(".txt"))

    def test_a_name_of_symbols_is_stored(self):
        for name in ["@@", "📄", "📄.png", ".."]:
            with self.subTest(name=name):
                attachment = upload(self.project, self.ada, name=name, content=b"x")
                self.assertEqual(attachment.name, name)
                self.assertTrue(attachment.file.name.startswith("files/"))

    def test_the_upload_endpoint_takes_odd_names(self):
        self.client.force_login(self.ada)
        for name in ["ä" * 200 + ".txt", "@@", "📄"]:
            with self.subTest(name=name):
                response = self.client.post(
                    f"/projects/{self.project.pk}/attachments/",
                    {"file": SimpleUploadedFile(name, b"x")},
                )
                self.assertEqual(response.status_code, 201)

    def test_the_new_file_form_takes_odd_names(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/projects/{self.project.pk}/files/new/",
            {"files": [SimpleUploadedFile("@@", b"x")]},
        )
        self.assertEqual(response.status_code, 302)

    def test_the_extension_survives_shortening(self):
        attachment = upload(self.project, self.ada, name="a" * 300 + ".pdf")
        self.assertTrue(attachment.file.name.endswith(".pdf"))


class RollbackTest(Fixture, TestCase):
    def test_a_failed_upload_leaves_no_file(self):
        with (
            patch.object(Attachment, "save", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            upload(self.project, self.ada)
        self.assertEqual(stored_files(self.project), [])

    def test_a_failed_new_file_leaves_no_file(self):
        with (
            patch.object(attachments, "link", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            ops.create_upload(
                project=self.project,
                file=ContentFile(b"x", name="a.txt"),
                creator=self.ada,
            )
        self.assertEqual(stored_files(self.project), [])

    def test_a_failed_replacement_keeps_only_the_old_file(self):
        from biwak.files import operations as file_ops

        item = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
        )
        before = stored_files(self.project)
        with (
            patch.object(file_ops, "record", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            file_ops.replace_upload(
                item, ContentFile(b"y", name="b.txt"), actor=self.ada
            )
        self.assertEqual(stored_files(self.project), before)
