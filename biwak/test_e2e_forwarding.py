"""Forwarded mails in the browser (specs/forwarding.md): filing one as a
to-do in the dialog, choosing the list's group in the combobox, the note
while a list clients see is chosen, and
deleting one after the question"""

from biwak.forwarding import operations as forwarding
from biwak.forwarding.models import ForwardedMail
from biwak.forwarding.support import sample
from biwak.inbound.support import replying
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_e2e import E2ETestCase, expect


@replying
class ForwardedTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.todolist = ops.create_list(
            project=self.project, title="Website fixes", creator=self.ada
        )
        self.group = ops.create_group(todolist=self.todolist.todolist, title="Footer")
        self.forwarded = forwarding.store(self.ada, sample("apple_mail_en.eml"))

    def test_file_as_todo_in_the_dialog(self):
        page = self.page
        self.goto(page, "/forwarded/")
        row = page.locator(f"[data-forwarded='{self.forwarded.pk}']")
        row.get_by_role("link", name="File as to-do…").click()
        dialog = page.get_by_role("dialog", name="File as to-do")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label("Title")).to_have_value("Broken link in the footer")
        field = dialog.get_by_role("combobox", name="List and group")
        field.fill("footer")
        listbox = dialog.get_by_role("listbox")
        listbox.get_by_role("option", name="Website fixes / Footer").click()
        dialog.get_by_role("button", name="Add to-do").click()
        todo = Item.objects.filter(kind="todo")
        page.wait_for_url("**/todos/*/")
        self.assertEqual(todo.get().todo.group, self.group)
        expect(page.get_by_text("goes to a 404")).to_be_visible()
        self.assertFalse(ForwardedMail.objects.exists())
        self.assertEqual(self.errors, [])

    def test_the_note_follows_a_list_clients_see(self):
        ops.create_list(
            project=self.project, title="Client wishes", creator=self.ada, visible=True
        )
        page = self.page
        self.goto(page, "/forwarded/")
        page.get_by_role("link", name="File as to-do…").click()
        dialog = page.get_by_role("dialog", name="File as to-do")
        note = dialog.locator("#clients-note")
        expect(note).to_be_hidden()
        field = dialog.get_by_role("combobox", name="List and group")
        listbox = dialog.get_by_role("listbox")
        field.fill("wishes")
        listbox.get_by_role(
            "option", name="Client wishes (clients can see this)"
        ).click()
        expect(note).to_be_visible()
        field.fill("footer")
        listbox.get_by_role("option", name="Website fixes / Footer").click()
        expect(note).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_delete_after_the_question(self):
        page = self.page
        self.goto(page, "/forwarded/")
        page.get_by_role("link", name="Delete").click()
        dialog = page.get_by_role("dialog", name="Delete the forwarded mail?")
        dialog.get_by_role("button", name="Delete").click()
        expect(page.get_by_text("Nothing forwarded.")).to_be_visible()
        self.assertFalse(ForwardedMail.objects.exists())
        self.assertEqual(self.errors, [])
