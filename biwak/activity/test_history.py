import datetime as dt
from unittest import mock

from django.test import TestCase

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import APIToken
from biwak.activity import history
from biwak.audit.models import LoggedAction
from biwak.checkins import operations as checkins
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import person, project


class HistoryTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal plans", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.group = ops.create_group(todolist=self.shared.todolist, title="Later")
        self.todo = ops.create_todo(
            todolist=self.internal,
            title="Draft",
            creator=self.ada,
            notes="One\nTwo\nThree",
        )
        LoggedAction.objects.all().delete()

    def item(self):
        return Item.objects.get(pk=self.todo.pk)

    def changes(self):
        """(who, label, old, new) oldest first"""
        return [
            (c.user.get_short_name() if c.user else c.user_name, c.label, c.old, c.new)
            for c in reversed(history.history(self.item(), self.ada))
        ]

    def test_list_page_links_to_its_history(self):
        url = f"/items/{self.shared.pk}/history/"
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(self.shared.get_absolute_url()), url)
        # Clients have no history
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get(self.shared.get_absolute_url()), url)

    def test_history_of_a_todo(self):
        self.client.force_login(self.ada)
        self.client.post(
            f"/todos/{self.todo.pk}/",
            {
                "form": "todo",
                "title": "Final",
                "notes": "One\nTwo changed\nThree",
                "due_on": "2026-12-01",
                "assignees": [],
            },
        )
        ops.assign(self.item(), [self.bob], actor=self.ada)
        self.client.force_login(self.bob)
        self.client.post(f"/todos/{self.todo.pk}/toggle/", {"done": "1"})
        ops.move_todo(
            self.item(), todolist=self.shared, group=self.group, actor=self.bob
        )
        set_user_name(self.bob)
        ops.unassign(self.item(), [self.bob], actor=self.bob)
        changes = self.changes()
        when = changes[4][3]
        self.assertRegex(when, r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(
            changes,
            [
                ("Ada", "Title", "Draft", "Final"),
                ("Ada", "Notes", "One\nTwo\nThree", "One\nTwo changed\nThree"),
                ("Ada", "Due on", None, "2026-12-01"),
                ("Ada", "Assigned", None, "Bob Example"),
                ("Bob", "Completed", None, when),
                ("Bob", "List", "Internal plans", "Shared"),
                ("Bob", "Group", None, "Later"),
                ("Bob", "Visible to clients", "no", "yes"),
                ("Bob", "Unassigned", None, "Bob Example"),
            ],
        )

    def test_notes_as_a_diff(self):
        set_user_name(self.ada)
        ops.update_todo(
            self.item(),
            actor=self.ada,
            notes="One\nTwo\nThree\nFour\nFive\nSix\nSeven\nEight",
        )
        ops.update_todo(
            self.item(),
            actor=self.ada,
            notes="One\n2\nThree\nFour\nFive\nSix\nSeven\n8",
        )
        latest, first = history.history(self.item(), self.ada)
        self.assertEqual(
            latest.diff,
            [
                (" ", "One"),
                ("-", "Two"),
                ("+", "2"),
                (" ", "Three"),
                ("…", ""),
                (" ", "Seven"),
                ("-", "Eight"),
                ("+", "8"),
            ],
        )
        self.assertEqual(first.diff[-1], ("+", "Eight"))

    def test_names_link_to_the_persons_page(self):
        set_user_name(self.bob)
        ops.update_todo(self.item(), actor=self.bob, title="Final")
        self.client.force_login(self.ada)
        response = self.client.get(f"/items/{self.todo.pk}/history/")
        self.assertContains(
            response, f'<a href="/people/{self.bob.pk}/" class="wb-person-link">Bob</a>'
        )

    def test_who_is_not_always_a_person(self):
        set_user_name("Fairy tasks")
        ops.update_todo(self.item(), actor=self.ada, title="Changed")
        (change,) = history.history(self.item(), self.ada)
        self.assertIsNone(change.user)
        self.assertEqual(change.user_name, "Fairy tasks")

    def test_list_switch_and_creation(self):
        set_user_name(self.ada)
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        (change,) = history.history(Item.objects.get(pk=self.internal.pk), self.ada)
        self.assertEqual(
            (change.label, change.old, change.new), ("Visible to clients", "no", "yes")
        )
        LoggedAction.objects.all().delete()
        new = ops.create_todo(todolist=self.internal, title="New", creator=self.ada)
        (created, *_rest) = reversed(history.history(new, self.ada))
        self.assertEqual((created.kind, created.new), ("created", "New"))

    def test_titles_of_lists_viewers_cant_see(self):
        ops.move_todo(self.item(), todolist=self.shared, actor=self.ada)
        change = next(
            c for c in history.history(self.item(), self.cleo) if c.label == "List"
        )
        self.assertEqual((change.old, change.new), ("another list", "Shared"))

    def test_page_for_staff_only(self):
        ops.update_todo(self.item(), actor=self.ada, title="Final")
        url = f"/items/{self.todo.pk}/history/"
        self.client.force_login(self.ada)
        response = self.client.get(url)
        self.assertContains(response, "Final")
        self.assertContains(response, "Draft")
        self.assertContains(self.client.get(f"/todos/{self.todo.pk}/"), url)
        # Clients: a 404 for what they can't see, a 403 for the rest
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(url).status_code, 404)
        visible = ops.create_todo(todolist=self.shared, title="Open", creator=self.ada)
        self.assertEqual(
            self.client.get(f"/items/{visible.pk}/history/").status_code, 403
        )
        self.assertNotContains(self.client.get(visible.get_absolute_url()), "/history/")

    def test_api(self):
        ops.update_todo(self.item(), actor=self.ada, title="Final", notes="Other")

        def get(user, pk):
            _token, secret = APIToken.create_for(user=user, title="T", access="read")
            return self.client.get(
                f"/api/v1/items/{pk}/history/",
                headers={"authorization": f"Bearer {secret}"},
            )

        response = get(self.ada, self.todo.pk)
        self.assertEqual(response.status_code, 200)
        fields = {c["field"]: c for c in response.json()}
        self.assertEqual(
            (fields["title"]["old"], fields["title"]["new"]), ("Draft", "Final")
        )
        self.assertEqual(fields["notes"]["diff"][-1], {"op": "+", "text": "Other"})
        self.assertEqual(get(self.cleo, self.todo.pk).status_code, 404)
        visible = ops.create_todo(todolist=self.shared, title="Open", creator=self.ada)
        self.assertEqual(get(self.cleo, visible.pk).status_code, 403)


class FolderHistoryTest(TestCase):
    def test_moving_a_doc(self):
        ada = person("Ada")
        p = project(members=[ada])
        folder = ops.create_folder(project=p, title="Contracts", creator=ada)
        doc = ops.create_doc(project=p, title="Offer", creator=ada)
        LoggedAction.objects.all().delete()
        ops.move_item(doc, parent=folder, actor=ada)
        (change,) = history.history(Item.objects.get(pk=doc.pk), ada)
        self.assertEqual((change.label, change.new), ("Folder", "Contracts"))


class CheckinHistoryTest(CheckinTestCase):
    """The audited tables of check-ins: answers' texts, the questions'
    schedules and people"""

    def test_answer(self):
        self.run_at("2027-03-22 09:00")
        answer = checkins.answer(self.item, user=self.bob, content="Fine")
        LoggedAction.objects.all().delete()
        checkins.answer(self.item, user=self.bob, content="Fine, thanks")
        (change,) = history.history(Item.objects.get(pk=answer.pk), self.ada)
        self.assertEqual(
            (change.label, change.old, change.new), ("Content", "Fine", "Fine, thanks")
        )

    def test_question(self):
        LoggedAction.objects.all().delete()
        checkins.update_question(
            self.item,
            actor=self.ada,
            rule="FREQ=WEEKLY;BYDAY=TU",
            time_of_day=dt.time(10, 0),
        )
        checkins.pause(self.item, actor=self.ada)
        checkins.set_people(self.item, [self.ada], actor=self.ada)
        changes = [
            (c.label, c.old, c.new)
            for c in reversed(history.history(self.item, self.ada))
        ]
        self.assertEqual(
            changes,
            [
                ("Schedule", "every Monday", "every Tuesday"),
                ("Time of day", "09:00", "10:00"),
                ("Paused", None, mock.ANY),
                ("No longer asked", None, "Bob Example"),
            ],
        )
