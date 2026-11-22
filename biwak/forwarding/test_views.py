"""The "Forwarded" page, filing and deleting through the pages
(specs/forwarding.md): only the forwarder sees a forwarded mail"""

import datetime as dt

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from biwak.activity.mails import send_mails
from biwak.activity.operations import subscribe
from biwak.files.models import Attachment
from biwak.forwarding import operations
from biwak.forwarding.models import ForwardedMail
from biwak.forwarding.support import IMAGE
from biwak.forwarding.test_operations import FilingTestCase
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.palette.test_actions import palette_data
from biwak.test_utils import (
    assert_modal,
    assert_modal_redirect,
    external,
    person,
    project,
)


MODAL = {"HTTP_HX_MODAL": "true", "HTTP_HX_REQUEST": "true"}


class ForwardedPageTest(FilingTestCase):
    def test_own_mails_newest_first(self):
        first = self.forwarded("gmail_en.eml")
        second = self.forwarded("outlook_en.eml")
        self.forwarded(user=self.bea)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("forwarded"))
        content = response.content.decode()
        self.assertContains(response, "inbox@reply.example.org")
        self.assertContains(response, "deleted after 30 days")
        self.assertLess(
            content.index(f'data-forwarded="{second.pk}"'),
            content.index(f'data-forwarded="{first.pk}"'),
        )
        self.assertEqual(content.count("data-forwarded="), 2)
        self.assertContains(
            response, "From Dora Example &lt;dora@example.com&gt;, 20 Nov 2026"
        )
        self.assertContains(response, "To: Ada Example &lt;ada@example.org&gt;")
        # The image inline, at the storage's URL (specs/files.md)
        image = second.files.get(name="image001.png")
        self.assertContains(
            response,
            f'<img class="wb-attachment-image" loading="lazy" src="{image.file.url}"',
        )
        self.assertContains(response, "<strong>revised quote</strong>", html=True)
        # The count in the person menu
        self.assertContains(
            response, '<span class="badge wb-tone-neutral ms-1">2</span>'
        )

    def test_empty(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("forwarded"))
        self.assertContains(response, "Nothing forwarded.")
        self.assertNotContains(response, "wb-tone-neutral ms-1")

    def test_externals_have_it(self):
        pia = external("Pia")
        self.client.force_login(pia)
        self.assertEqual(self.client.get(reverse("forwarded")).status_code, 200)

    def test_not_for_clients(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(reverse("forwarded")).status_code, 404)
        response = self.client.get(reverse("projects"))
        self.assertNotContains(response, reverse("forwarded"))
        labels = [action["label"] for action in palette_data(response)["actions"]]
        self.assertNotIn("Forwarded", labels)

    def test_in_the_menu_and_the_palette(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("projects"))
        self.assertContains(response, f'href="{reverse("forwarded")}"')
        actions = {a["label"]: a for a in palette_data(response)["actions"]}
        self.assertEqual(actions["Forwarded"]["url"], reverse("forwarded"))

    @override_settings(REPLY_DOMAIN="")
    def test_off_without_the_reply_domain(self):
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(reverse("forwarded")).status_code, 404)
        response = self.client.get(reverse("projects"))
        self.assertNotContains(response, reverse("forwarded"))
        labels = [action["label"] for action in palette_data(response)["actions"]]
        self.assertNotIn("Forwarded", labels)

    def test_nobody_else_sees_a_forwarded_mail(self):
        forwarded = self.forwarded()
        image = forwarded.files.get(name="image001.png")
        for user in [self.bea, self.cleo]:
            self.client.force_login(user)
            for url in [
                reverse("forwarded_file_message", args=[forwarded.pk]),
                reverse("forwarded_file_todo", args=[forwarded.pk]),
                reverse("forwarded_delete", args=[forwarded.pk]),
                image.get_absolute_url(),
            ]:
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 404)
                    if url != image.get_absolute_url():
                        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(ForwardedMail.objects.filter(pk=forwarded.pk).exists())

    def test_download(self):
        image = self.forwarded().files.get(name="image001.png")
        self.client.force_login(self.ada)
        response = self.client.get(image.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), IMAGE)
        self.assertEqual(response["Content-Type"], "image/png")


class FileThroughThePageTest(FilingTestCase):
    def test_file_as_message(self):
        forwarded = self.forwarded()
        url = reverse("forwarded_file_message", args=[forwarded.pk])
        self.client.force_login(self.ada)
        response = self.client.get(url, **MODAL)
        assert_modal(self, response, title="File as message")
        self.assertContains(response, 'value="Revised quote for the landing page"')
        self.assertContains(response, "data-combobox")
        response = self.client.post(
            url,
            {"title": "Quote", "project": self.project.pk, "category": ""},
            **MODAL,
        )
        item = Item.objects.get(kind="message")
        assert_modal_redirect(self, response, item.get_absolute_url())
        self.assertEqual(item.title, "Quote")
        self.assertFalse(item.is_client_visible)
        self.assertEqual(Attachment.objects.filter(item=item).count(), 2)
        self.assertFalse(ForwardedMail.objects.exists())

    def test_only_projects_the_person_opens(self):
        limited = project("Payroll", members=[self.bea], all_access=False)
        archived = project("Old")
        archived.archived_at = timezone.now()
        archived.save()
        forwarded = self.forwarded()
        url = reverse("forwarded_file_message", args=[forwarded.pk])
        self.client.force_login(self.ada)
        response = self.client.get(url)
        self.assertContains(response, f'<option value="{self.project.pk}">')
        self.assertNotContains(response, "Payroll")
        self.assertNotContains(response, ">Old<")
        response = self.client.post(url, {"title": "Quote", "project": limited.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(kind="message").exists())

    def test_file_as_todo_into_a_group(self):
        group = ops.create_group(todolist=self.internal.todolist, title="Bugs")
        forwarded = self.forwarded("apple_mail_en.eml")
        url = reverse("forwarded_file_todo", args=[forwarded.pk])
        self.client.force_login(self.ada)
        response = self.client.get(url, **MODAL)
        assert_modal(self, response, title="File as to-do")
        # Grouped by project
        self.assertContains(response, '<optgroup label="Website">')
        self.assertContains(response, f'<option value="{self.internal.pk}">')
        self.assertContains(
            response, f'<option value="{self.internal.pk}:{group.pk}">Internal / Bugs'
        )
        response = self.client.post(
            url,
            {
                "title": "Fix the footer link",
                "target": f"{self.internal.pk}:{group.pk}",
            },
            **MODAL,
        )
        todo = Item.objects.get(kind="todo")
        assert_modal_redirect(self, response, todo.get_absolute_url())
        self.assertEqual(todo.title, "Fix the footer link")
        self.assertEqual(todo.todo.group, group)
        self.assertIn("goes to a 404", todo.todo.notes)
        self.assertFalse(ForwardedMail.objects.exists())

    def test_lists_clients_see_are_marked_with_the_note(self):
        forwarded = self.forwarded("apple_mail_en.eml")
        url = reverse("forwarded_file_todo", args=[forwarded.pk])
        self.client.force_login(self.ada)
        response = self.client.get(url, **MODAL)
        self.assertContains(
            response,
            f'<option value="{self.shared.pk}" data-client="true">'
            "Shared (clients can see this)</option>",
            html=True,
        )
        # The note is there, hidden until such a list is chosen
        self.assertContains(response, 'id="clients-note" hidden')
        response = self.client.post(
            url, {"title": "", "target": str(self.shared.pk)}, **MODAL
        )
        self.assertContains(response, 'id="clients-note" >')
        response = self.client.post(
            url, {"title": "Footer", "target": str(self.shared.pk)}, **MODAL
        )
        todo = Item.objects.get(kind="todo")
        assert_modal_redirect(self, response, todo.get_absolute_url())
        self.assertTrue(todo.is_client_visible)

    def test_delete_asks_first(self):
        forwarded = self.forwarded()
        url = reverse("forwarded_delete", args=[forwarded.pk])
        self.client.force_login(self.ada)
        response = self.client.get(url, **MODAL)
        assert_modal(self, response, title="Delete the forwarded mail?")
        self.assertContains(response, "can&#x27;t be restored")
        self.assertTrue(ForwardedMail.objects.exists())
        response = self.client.post(url, **MODAL)
        assert_modal_redirect(self, response, reverse("forwarded"))
        self.assertFalse(ForwardedMail.objects.exists())


class FiledItemsVisibilityTest(FilingTestCase):
    def test_clients_get_404_for_the_filed_message(self):
        item = operations.file_as_message(
            self.forwarded(), project=self.project, title="Quote", actor=self.ada
        )
        attachment = Attachment.objects.filter(item=item).first()
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.assertEqual(
            self.client.get(attachment.get_absolute_url()).status_code, 404
        )
        self.client.force_login(self.bea)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 200)

    def test_clients_dont_find_the_filed_message_anywhere(self):
        item = operations.file_as_message(
            self.forwarded(),
            project=self.project,
            title="Zebra crossing",
            actor=self.ada,
        )
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get(reverse("feed")), "Zebra crossing")
        self.assertNotContains(
            self.client.get(reverse("search"), {"q": "revised quote"}), "Zebra crossing"
        )
        self.assertEqual(
            self.client.get(f"/api/v1/messages/{item.pk}/").status_code, 404
        )
        self.client.force_login(self.bea)
        self.assertContains(self.client.get(reverse("feed")), "Zebra crossing")
        self.assertContains(
            self.client.get(reverse("search"), {"q": "revised quote"}), "Zebra crossing"
        )

    def test_clients_see_a_todo_filed_into_their_list(self):
        subscribe(self.cleo, self.shared)
        with self.captureOnCommitCallbacks(execute=True):
            item = operations.file_as_todo(
                self.forwarded("outlook_en.eml"),
                todolist=self.shared,
                title="Zebra crossing",
                actor=self.ada,
            )
        image = Attachment.objects.filter(item=item, name="image001.png").get()
        self.client.force_login(self.cleo)
        response = self.client.get(item.get_absolute_url())
        self.assertContains(response, "Forwarded from Dora Example")
        self.assertContains(response, image.file.url)
        self.assertEqual(self.client.get(image.get_absolute_url()).status_code, 200)
        self.assertContains(self.client.get(reverse("feed")), "Zebra crossing")
        self.assertContains(
            self.client.get(reverse("search"), {"q": "revised quote"}),
            "Zebra crossing",
        )
        self.assertEqual(self.client.get(f"/api/v1/todos/{item.pk}/").status_code, 200)
        # The mail about the new to-do carries the text and the files
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        [message] = [m for m in mail.outbox if m.to == [self.cleo.email]]
        self.assertIn("Forwarded from Dora Example", message.body)
        self.assertIn("image001.png", message.body)

    def test_clients_get_404_for_the_filed_todo(self):
        item = operations.file_as_todo(
            self.forwarded("gmail_en.eml"),
            todolist=self.internal,
            title="Export",
            actor=self.ada,
        )
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)

    def test_staff_without_access_dont_see_it_either(self):
        dan = person("Dan", organization="Example External Agency")
        self.client.force_login(dan)
        self.assertEqual(
            self.client.get(
                reverse("forwarded_file_message", args=[self.forwarded().pk])
            ).status_code,
            404,
        )
