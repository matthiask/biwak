"""The actions of each page, as rendered into the JSON script of
``base.html``: only what the person may run (specs/keyboard.md), as staff,
as a client and as staff without access to a limited project"""

import json
import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from biwak.activity.operations import subscribe
from biwak.bookmarks import operations as bookmark_ops
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9, at
from biwak.items import operations as ops
from biwak.test_utils import person, project


def palette_data(response):
    match = re.search(
        r'<script id="wb-palette-data" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.DOTALL,
    )
    return json.loads(match[1]) if match else None


class ActionsBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")  # Staff, not a member of the limited project
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        self.limited = project("Payroll", members=[self.ada], all_access=False)
        self.list = ops.create_list(
            project=self.camp, title="Launch", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(todolist=self.list, title="Tent", creator=self.ada)
        self.message = ops.create_message(
            project=self.camp, title="Hello", creator=self.ada, visible=True
        )
        self.doc = ops.create_doc(
            project=self.camp, title="Plan", creator=self.ada, visible=True
        )
        self.file = ops.create_upload(
            project=self.camp,
            file=SimpleUploadedFile("a.png", b"x"),
            creator=self.ada,
            visible=True,
        )
        self.question = checkin_ops.create_question(
            project=self.camp,
            title="Weather?",
            creator=self.ada,
            people=[self.ada],
            now=at("2027-03-19 12:00"),
            visible=True,
            **MONDAY_9,
        )

    def actions(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return {a["label"]: a for a in palette_data(response)["actions"]}


class EverywhereTest(ActionsBase):
    def test_the_actions_every_page_has(self):
        for user in [self.ada, self.cleo]:
            actions = self.actions(user, "/")
            for label in [
                "Go to projects",
                "Go to the activity",
                "Go to my to-dos",
                "Go to bookmarks",
                "Notification settings",
                "Search",
                "Switch the theme",
            ]:
                self.assertIn(label, actions)
            self.assertEqual(actions["Go to bookmarks"]["shortcut"], "g b")
            self.assertEqual(actions["Go to my to-dos"]["url"], "/todos/?assignee=me")

    def test_new_project_is_for_staff(self):
        self.assertIn("New project", self.actions(self.ada, "/"))
        self.assertNotIn("New project", self.actions(self.cleo, "/"))

    def test_only_for_people_who_are_logged_in(self):
        response = self.client.get("/accounts/login/")
        self.assertIsNone(palette_data(response))
        self.assertNotContains(response, "wb-palette")

    def test_the_setting_and_the_dialog(self):
        self.client.force_login(self.ada)
        data = palette_data(self.client.get("/"))
        self.assertTrue(data["shortcuts"])
        self.ada.keyboard_shortcuts = False
        self.ada.save()
        self.assertFalse(palette_data(self.client.get("/"))["shortcuts"])

    def test_the_dialog_has_roles_and_labels_for_screen_readers(self):
        self.client.force_login(self.ada)
        content = self.client.get("/").content.decode()
        self.assertIn('<dialog\n  id="wb-palette"', content)
        for attribute in [
            'aria-labelledby="wb-palette-title"',
            'role="combobox"',
            'aria-controls="wb-palette-list"',
            'aria-autocomplete="list"',
            'aria-expanded="true"',
            'aria-label="Search or run a command"',
            'role="listbox"',
            'aria-label="Results"',
            'role="status"',
            'aria-live="polite"',
            'aria-labelledby="wb-shortcuts-title"',
        ]:
            self.assertIn(attribute, content)
        self.assertIn('<h2 id="wb-palette-title" class="visually-hidden">', content)


class ProjectActionsTest(ActionsBase):
    def test_staff(self):
        actions = self.actions(self.ada, f"/projects/{self.camp.pk}/")
        for label in [
            "New list",
            "New message",
            "New doc",
            "Upload a file",
            "New check-in",
            "The project's activity",
            "People",
            "Docs and files",
            "To-dos by due date",
        ]:
            self.assertEqual(actions[label]["group"], "page", label)
        # On the page with the form it focuses it
        self.assertEqual(actions["New list"]["type"], "focus")
        self.assertEqual(
            actions["New message"]["url"], f"/projects/{self.camp.pk}/messages/new/"
        )

    def test_a_client_gets_what_clients_may_do(self):
        actions = self.actions(self.cleo, f"/projects/{self.camp.pk}/")
        self.assertIn("New message", actions)
        self.assertIn("To-dos by due date", actions)
        for label in ["New list", "New doc", "Upload a file", "New check-in"]:
            self.assertNotIn(label, actions)

    def test_other_project_pages_link_to_the_form_of_the_project_page(self):
        actions = self.actions(self.ada, f"/projects/{self.camp.pk}/messages/")
        self.assertEqual(actions["New list"]["type"], "link")
        self.assertEqual(
            actions["New list"]["url"], f"/projects/{self.camp.pk}/#new-list"
        )

    def test_the_folder_of_a_new_doc(self):
        folder = ops.create_folder(project=self.camp, title="Maps", creator=self.ada)
        actions = self.actions(self.ada, folder.get_absolute_url())
        self.assertEqual(
            actions["New doc"]["url"],
            f"/projects/{self.camp.pk}/docs/new/?folder={folder.pk}",
        )
        self.assertIn("Bookmark", actions)

    def test_staff_without_access_to_a_limited_project_get_nothing(self):
        self.client.force_login(self.bob)
        for url in [
            f"/projects/{self.limited.pk}/",
            f"/projects/{self.limited.pk}/messages/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_no_page_actions_on_other_pages(self):
        actions = self.actions(self.ada, "/")
        self.assertEqual({a["group"] for a in actions.values()}, {"everywhere"})
        actions = self.actions(self.ada, f"/projects/{self.camp.pk}/edit/")
        self.assertEqual({a["group"] for a in actions.values()}, {"everywhere"})


class ItemActionsTest(ActionsBase):
    def test_a_list(self):
        actions = self.actions(self.ada, self.list.get_absolute_url())
        self.assertEqual(actions["New to-do"]["type"], "focus")
        self.assertIn("Board view", actions)
        self.assertIn("Edit", actions)
        self.assertIn("History", actions)
        actions = self.actions(self.ada, self.list.get_absolute_url() + "?view=board")
        self.assertIn("List view", actions)
        self.assertNotIn("Board view", actions)

    def test_a_list_as_a_client(self):
        actions = self.actions(self.cleo, self.list.get_absolute_url())
        self.assertIn("New to-do", actions)
        self.assertIn("Bookmark", actions)
        # Not theirs: no edit; no history for clients
        self.assertNotIn("Edit", actions)
        self.assertNotIn("History", actions)
        self.assertNotIn("New list", actions)

    def test_a_to_do(self):
        for user in [self.ada, self.cleo]:
            actions = self.actions(user, self.todo.get_absolute_url())
            self.assertEqual(actions["Complete"]["shortcut"], "x")
            self.assertEqual(actions["Complete"]["type"], "post")
            self.assertEqual(
                actions["Complete"]["url"], f"/todos/{self.todo.pk}/toggle/"
            )
            self.assertEqual(actions["Comment"]["shortcut"], "c")
            # Everybody who sees a to-do edits it
            self.assertEqual(actions["Edit"]["shortcut"], "e")
            self.assertEqual(actions["Copy the link"]["type"], "copy")
            self.assertTrue(
                actions["Copy the link"]["text"].endswith(f"/todos/{self.todo.pk}/")
            )
        ops.complete(self.todo, actor=self.ada)
        self.assertIn("Reopen", self.actions(self.ada, self.todo.get_absolute_url()))

    def test_toggles_follow_the_state(self):
        url = self.todo.get_absolute_url()
        actions = self.actions(self.ada, url)
        self.assertEqual(actions["Bookmark"]["data"], {"bookmark": "1"})
        self.assertEqual(actions["Bookmark"]["url"], f"/items/{self.todo.pk}/bookmark/")
        bookmark_ops.add_bookmark(self.ada, item=self.todo)
        subscribe(self.ada, self.todo)
        actions = self.actions(self.ada, url)
        self.assertIn("Remove the bookmark", actions)
        self.assertIn("Unsubscribe", actions)
        self.assertEqual(actions["Unsubscribe"]["data"], {})
        self.assertNotIn("Bookmark", actions)

    def test_history_is_for_staff(self):
        url = self.todo.get_absolute_url()
        self.assertIn("History", self.actions(self.ada, url))
        self.assertNotIn("History", self.actions(self.cleo, url))

    def test_edit_follows_who_may_change(self):
        for item in [self.message, self.doc, self.file]:
            url = item.get_absolute_url()
            self.assertEqual(self.actions(self.ada, url)["Edit"]["shortcut"], "e")
            # Clients change only what they created
            self.assertNotIn("Edit", self.actions(self.cleo, url), url)
        mine = ops.create_message(
            project=self.camp, title="From Cleo", creator=self.cleo, visible=True
        )
        self.assertIn("Edit", self.actions(self.cleo, mine.get_absolute_url()))
        self.assertEqual(
            self.actions(self.cleo, mine.get_absolute_url())["Edit"]["url"],
            f"/messages/{mine.pk}/edit/",
        )

    def test_check_in_questions(self):
        url = self.question.get_absolute_url()
        self.assertIn("Edit", self.actions(self.ada, url))
        actions = self.actions(self.cleo, url)
        self.assertNotIn("Edit", actions)
        # Questions have no comments
        self.assertNotIn("Comment", actions)

    def test_hidden_items_have_no_page_for_clients(self):
        internal = ops.create_list(
            project=self.camp, title="Internal", creator=self.ada
        )
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(internal.get_absolute_url()).status_code, 404)

    def test_forms_have_the_actions_of_everywhere_only(self):
        actions = self.actions(self.ada, f"/messages/{self.message.pk}/edit/")
        self.assertEqual({a["group"] for a in actions.values()}, {"everywhere"})
