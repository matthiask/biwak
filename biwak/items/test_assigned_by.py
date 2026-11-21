"""Who assigned (specs/ui-round-5.md, section 4): the through model, the
operations, the filter, the API and the palette"""

import datetime as dt

from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.items.models import Assignment
from biwak.palette.test_actions import palette_data
from biwak.test_utils import person, project


class AssignedByTestCase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )

    def todo(self, title, *, assignees=(), creator=None, todolist=None):
        return ops.create_todo(
            todolist=todolist or self.shared,
            title=title,
            creator=creator or self.ada,
            assignees=assignees,
        )

    def assigner(self, item, user):
        return Assignment.objects.get(todo_id=item.pk, user=user).assigned_by


class OperationsTest(AssignedByTestCase):
    def test_assign_records_the_actor_and_when(self):
        item = self.todo("Pack")
        ops.assign(item, [self.bob], actor=self.ada)
        assignment = Assignment.objects.get(todo_id=item.pk)
        self.assertEqual(assignment.assigned_by, self.ada)
        self.assertLess(
            abs(assignment.assigned_at.timestamp() - dt.datetime.now().timestamp()),
            60,
        )

    def test_creating_a_to_do_with_assignees_records_the_creator(self):
        item = self.todo("Pack", assignees=[self.bob, self.ada])
        self.assertEqual(self.assigner(item, self.bob), self.ada)
        self.assertEqual(self.assigner(item, self.ada), self.ada)

    def test_somebody_gives_themselves_a_to_do(self):
        item = self.todo("Pack")
        ops.assign(item, [self.bob], actor=self.bob)
        self.assertEqual(self.assigner(item, self.bob), self.bob)

    def test_editing_assigns_through_the_operation(self):
        item = self.todo("Pack", assignees=[self.ada])
        ops.update_todo(item, assignees=[self.ada, self.bob], actor=self.bob)
        self.assertEqual(self.assigner(item, self.ada), self.ada)
        self.assertEqual(self.assigner(item, self.bob), self.bob)

    def test_unassigning_removes_the_row(self):
        item = self.todo("Pack", assignees=[self.ada, self.bob])
        ops.unassign(item, [self.bob], actor=self.ada)
        self.assertEqual(list(item.todo.assignees.all()), [self.ada])

    def test_the_assigner_can_be_given_or_left_empty(self):
        item = self.todo("Pack")
        ops.assign(item, [self.bob], actor=self.ada, assigned_by={})
        self.assertIsNone(self.assigner(item, self.bob))

    def test_deleting_the_assigner_keeps_the_assignment(self):
        dan = person("Dan")
        item = self.todo("Pack")
        # (A person with events can't be deleted; the key is what's tested)
        Assignment.objects.create(todo_id=item.pk, user=self.bob, assigned_by=dan)
        self.assertEqual(self.assigner(item, self.bob), dan)
        dan.delete()
        self.assertIsNone(self.assigner(item, self.bob))

    def test_the_next_recurring_to_do_keeps_each_assigner(self):
        item = ops.create_todo(
            todolist=self.shared,
            title="Water",
            creator=self.ada,
            due_on=dt.date(2026, 11, 20),
            recurrence="FREQ=DAILY",
        )
        ops.assign(item, [self.bob], actor=self.ada)
        ops.assign(item, [self.ada], actor=self.bob)
        ops.assign(item, [self.cleo], actor=self.ada, assigned_by={})
        ops.complete(item, actor=self.ada)
        following = item.following.get().item
        self.assertEqual(self.assigner(following, self.bob), self.ada)
        self.assertEqual(self.assigner(following, self.ada), self.bob)
        self.assertIsNone(self.assigner(following, self.cleo))


class FilterTest(AssignedByTestCase):
    def setUp(self):
        super().setUp()
        self.mine_to_bob = self.todo("To Bob", assignees=[self.bob])
        self.mine_to_me = self.todo("To me", assignees=[self.ada])
        self.bobs_to_ada = self.todo("Bob to Ada", creator=self.bob)
        ops.assign(self.bobs_to_ada, [self.ada], actor=self.bob)
        self.nobodys = self.todo("Nobody")
        self.internal_one = self.todo(
            "Internal", assignees=[self.bob], todolist=self.internal
        )
        # Assigned twice by Ada: still one row
        both = self.todo("Both", assignees=[self.bob])
        ops.assign(both, [self.ada], actor=self.ada)

    def found(self, user, **params):
        self.client.force_login(user)
        query = {"grouping": "due", "assignee": "anybody"} | params
        response = self.client.get("/todos/", query)
        self.assertEqual(response.status_code, 200)
        return sorted(
            t.title for _k, _l, todos in response.context["sections"] for t in todos
        )

    def test_by_me_to_anybody(self):
        self.assertEqual(
            self.found(self.ada, assigned_by="me"),
            ["Both", "Internal", "To Bob", "To me"],
        )
        self.assertEqual(self.found(self.bob, assigned_by="me"), ["Bob to Ada"])

    def test_assigned_by_anybody_is_the_default(self):
        self.assertEqual(len(self.found(self.ada, assigned_by="")), 6)

    def test_with_the_assignee_it_is_the_same_assignment(self):
        # Bob was assigned "Bob to Ada"'s... no: Ada gave Bob "To Bob" and
        # "Both"; Bob gave Ada "Bob to Ada"
        self.assertEqual(
            self.found(self.ada, assigned_by="me", assignee="me"),
            ["Both", "To me"],
        )
        self.assertEqual(
            self.found(self.ada, assigned_by="me", assignee=self.bob.pk),
            ["Both", "Internal", "To Bob"],
        )
        # What Bob gave Ada isn't what Ada gave herself, though she's on it
        self.assertNotIn(
            "Bob to Ada", self.found(self.ada, assigned_by="me", assignee="me")
        )
        self.assertEqual(self.found(self.ada, assigned_by="me", assignee="nobody"), [])

    def test_a_project_has_it_too(self):
        self.client.force_login(self.bob)
        response = self.client.get(
            f"/projects/{self.project.pk}/todos/", {"assigned_by": "me"}
        )
        self.assertContains(response, "Bob to Ada")
        self.assertNotContains(response, "To Bob")
        self.assertContains(response, 'name="assigned_by"')

    def test_nonsense_is_an_error(self):
        self.client.force_login(self.ada)
        response = self.client.get("/todos/", {"assigned_by": "bob"})
        self.assertContains(response, "Select a valid choice")

    def test_a_client_sees_only_what_they_may_see(self):
        # Ada assigned Cleo on a visible to-do and Bob on an internal one
        ops.assign(self.nobodys, [self.cleo], actor=self.ada)
        self.assertEqual(self.found(self.cleo, assigned_by="me"), [])
        self.assertEqual(self.found(self.cleo, assignee="me"), ["Nobody"])
        # Cleo gives herself a to-do, and gives one to Ada
        own = self.todo("Cleos", creator=self.cleo)
        ops.assign(own, [self.cleo, self.ada], actor=self.cleo)
        self.assertEqual(self.found(self.cleo, assigned_by="me"), ["Cleos"])
        # Not the staff's: that's Ada's
        self.assertNotIn("Internal", self.found(self.cleo, assigned_by="me"))

    def test_the_filter_has_a_form_field_for_everybody(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            self.assertContains(self.client.get("/todos/"), "assigned by")


class TitleTest(AssignedByTestCase):
    """The page's title follows the filters; the navigation says "To-dos"
    and is active on every view of the page (decided 2026-11-21)"""

    def test_titles(self):
        self.client.force_login(self.ada)
        for params, title in [
            ({"assignee": "me"}, "My to-dos"),
            ({"assignee": "me", "assigned_by": "me"}, "My to-dos"),
            ({"assignee": "anybody", "assigned_by": "me"}, "To-dos I assigned"),
            ({"assignee": "anybody"}, "To-dos"),
            ({}, "My to-dos"),
        ]:
            with self.subTest(params=params):
                response = self.client.get("/todos/", params)
                self.assertContains(response, f'<h1 class="wb-title">{title}</h1>')
                self.assertRegex(
                    response.content.decode(),
                    r'class="nav-link active"\s+href="/todos/"',
                )

    def test_the_navigation_says_to_dos(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("projects"))
        self.assertContains(response, ">To-dos</a>")
        self.assertNotContains(response, ">My to-dos</a>")


class APITest(AssignedByTestCase):
    def get(self, user, **params):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return self.client.get(
            "/api/v1/todos/", params, headers={"authorization": f"Bearer {secret}"}
        )

    def titles(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return sorted(t["title"] for t in response.json()["results"])

    def test_assignees_carry_who_assigned_them(self):
        item = self.todo("Pack", assignees=[self.bob])
        ops.assign(item, [self.cleo], actor=self.ada, assigned_by={})
        for user in [self.ada, self.cleo]:
            data = self.get(user).json()["results"][0]
            by_name = {a["short_name"]: a for a in data["assignees"]}
            self.assertEqual(by_name["Bob"]["assigned_by"]["id"], self.ada.pk)
            self.assertIsNone(by_name["Cleo"]["assigned_by"])
            self.assertIn("name", by_name["Bob"])

    def test_the_single_to_do_and_a_list_have_it_too(self):
        item = self.todo("Pack", assignees=[self.bob])
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        headers = {"authorization": f"Bearer {secret}"}
        data = self.client.get(f"/api/v1/todos/{item.pk}/", headers=headers).json()
        self.assertEqual(data["assignees"][0]["assigned_by"]["id"], self.ada.pk)
        data = self.client.get(
            f"/api/v1/lists/{self.shared.pk}/todos/", headers=headers
        ).json()
        self.assertEqual(data[0]["assignees"][0]["assigned_by"]["id"], self.ada.pk)

    def test_assigned_by_me(self):
        self.todo("To Bob", assignees=[self.bob])
        mine = self.todo("To me", assignees=[self.ada])
        self.todo("Bob's", creator=self.bob, assignees=[self.ada, self.bob])
        self.todo("Nobody")
        self.todo("Internal", assignees=[self.bob], todolist=self.internal)
        self.assertEqual(
            self.titles(self.get(self.ada)),
            sorted(["To Bob", "To me", "Bob's", "Nobody", "Internal"]),
        )
        self.assertEqual(
            self.titles(self.get(self.ada, assigned_by="me")),
            ["Internal", "To Bob", "To me"],
        )
        self.assertEqual(
            self.titles(self.get(self.ada, assigned_by="me", assignee="me")),
            ["To me"],
        )
        self.assertEqual(
            self.titles(self.get(self.ada, assigned_by="me", assignee=self.bob.pk)),
            ["Internal", "To Bob"],
        )
        self.assertEqual(self.get(self.ada, assigned_by="x").status_code, 400)
        # The same through the CLI's parameter; Bob assigned Ada "Bob's"
        self.assertEqual(self.titles(self.get(self.bob, assigned_by="me")), ["Bob's"])
        del mine

    def test_a_client_only_gets_what_they_may_see(self):
        self.todo("Internal", assignees=[self.bob], todolist=self.internal)
        visible = self.todo("Visible")
        ops.assign(visible, [self.cleo], actor=self.cleo)
        self.assertEqual(
            self.titles(self.get(self.cleo, assigned_by="me")), ["Visible"]
        )
        self.assertEqual(self.titles(self.get(self.cleo)), ["Visible"])


class PaletteTest(AssignedByTestCase):
    def test_every_page_offers_to_dos_i_assigned(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            for url in ["/", "/todos/", self.shared.get_absolute_url()]:
                data = palette_data(self.client.get(url))
                actions = {a["label"]: a for a in data["actions"]}
                action = actions["To-dos I assigned"]
                self.assertEqual(action["type"], "link")
                self.assertEqual(
                    action["url"], "/todos/?assignee=anybody&assigned_by=me"
                )
                # Exactly this, not the remembered filters
                self.assertTrue(action["exact"])
                self.assertNotIn("exact", actions["Go to to-dos"])


class MigrationTest(TransactionTestCase):
    """The through model takes over the automatic table with its rows"""

    before = [("items", "0009_merge_tick_editing")]

    def rows(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM items_todo_assignees ORDER BY id")
            columns = [c.name for c in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def test_rows_survive_and_get_no_assigner(self):
        ada, bob = person("Ada"), person("Bob")
        item = ops.create_todo(
            todolist=ops.create_list(
                project=project(members=[ada, bob]), title="Old", creator=ada
            ),
            title="Old",
            creator=ada,
            assignees=[ada, bob],
        )
        self.assertEqual(len(self.rows()), 2)
        self.assertIsNotNone(self.rows()[0]["assigned_by_id"])

        # Back to the automatic table: the rows stay, two columns less
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        rows = self.rows()
        self.assertEqual(
            [(r["todo_id"], r["user_id"]) for r in rows],
            [(item.pk, ada.pk), (item.pk, bob.pk)],
        )
        self.assertEqual(set(rows[0]), {"id", "todo_id", "user_id"})
        # Unique per to-do and user, as the automatic table had it
        with connection.cursor() as cursor, self.assertRaises(IntegrityError):
            cursor.execute(
                "INSERT INTO items_todo_assignees (todo_id, user_id) VALUES (%s, %s)",
                [item.pk, ada.pk],
            )

        # And forward again: the same rows without an assigner
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["assigned_by_id"] for r in rows}, {None})
        self.assertTrue(all(r["assigned_at"] for r in rows))
        self.assertEqual(
            {a.user for a in Assignment.objects.filter(todo_id=item.pk)}, {ada, bob}
        )
        with connection.cursor() as cursor:
            names = connection.introspection.get_constraints(
                cursor, "items_todo_assignees"
            )
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid ="
                " 'items_todo_assignees'::regclass AND tgname = 'audit_trigger_row'"
            )
            audited = cursor.fetchone()[0]
        self.assertIn("items_assignment_todo_user_uniq", names)
        self.assertEqual(audited, 1)
