"""The "More" menu of items' pages (items/_more_entries.html): the history
and the visibility switch live there, not on the page (decided 2026-11-22,
specs/ui.md and specs/access.md)"""

import datetime as dt

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from biwak.checkins import operations as checkin_ops
from biwak.items import operations as ops
from biwak.test_utils import person, project, tags


class MoreMenuTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        kwargs = {"project": self.project, "creator": self.ada}
        self.items = {
            "list": ops.create_list(title="Launch", **kwargs),
            "folder": ops.create_folder(title="Drafts", **kwargs),
            "message": ops.create_message(title="Kickoff", **kwargs),
            "doc": ops.create_doc(title="Notes", **kwargs),
            "file": ops.create_upload(
                file=SimpleUploadedFile("plan.txt", b"Plan"), **kwargs
            ),
            "question": checkin_ops.create_question(
                title="How are you?",
                rule="FREQ=WEEKLY;BYDAY=MO",
                starts_on=dt.date(2027, 3, 15),
                time_of_day=dt.time(9, 0),
                people=[self.ada],
                **kwargs,
            ),
        }
        todolist = ops.create_list(title="Shared", visible=True, **kwargs)
        self.todo = ops.create_todo(todolist=todolist, title="Call", creator=self.ada)

    def entries(self, item):
        html = self.client.get(item.get_absolute_url()).content.decode()
        return html, tags(html, cls="dropdown-item")

    def test_the_switch_and_the_history_only_in_the_menu(self):
        self.client.force_login(self.ada)
        for kind, item in self.items.items():
            with self.subTest(kind=kind):
                html, entries = self.entries(item)
                switch = reverse("switch", args=[item.pk])
                history = reverse("item_history", args=[item.pk])
                self.assertIn(
                    {"class": "dropdown-item", "href": switch, "data-modal": None},
                    entries,
                )
                self.assertIn({"class": "dropdown-item", "href": history}, entries)
                # Nothing else on the page leads there (the palette's JSON
                # has the history, escaped)
                self.assertEqual(html.count(f'"{switch}"'), 1)
                self.assertEqual(html.count(f'href="{history}"'), 1)
                self.assertNotIn("Hides it again", html)
                ops.set_visibility(item, visible=True, actor=self.ada)
                html = self.client.get(item.get_absolute_url()).content.decode()
                self.assertInHTML(
                    '<button type="submit" class="dropdown-item">Hide from clients</button>',
                    html,
                )
                self.assertEqual(html.count(f'action="{switch}"'), 1)

    def test_a_to_dos_history_in_the_menu(self):
        self.client.force_login(self.ada)
        html, entries = self.entries(self.todo)
        history = reverse("item_history", args=[self.todo.pk])
        self.assertIn({"class": "dropdown-item", "href": history}, entries)
        self.assertEqual(html.count(f'href="{history}"'), 1)
        # To-dos have no switch of their own
        self.assertNotIn(reverse("switch", args=[self.todo.pk]), html)

    def test_clients_get_neither(self):
        for item in self.items.values():
            ops.set_visibility(item, visible=True, actor=self.ada)
        self.client.force_login(self.cleo)
        for kind, item in [*self.items.items(), ("todo", self.todo)]:
            with self.subTest(kind=kind):
                html, _entries = self.entries(item)
                self.assertNotIn(reverse("switch", args=[item.pk]), html)
                self.assertNotIn(reverse("item_history", args=[item.pk]), html)
                self.assertNotIn("Hide from clients", html)
                # The tab stays
                self.assertIn("Clients can see this.", html)

    def test_creating_visible_stays(self):
        self.client.force_login(self.ada)
        response = self.client.get(
            reverse("folder_new", args=[self.project.pk]), headers={"HX-Modal": "1"}
        )
        self.assertContains(response, 'name="visible"')
