"""Filters on a list and its board (specs/todos.md, "Filters on a list")"""

import re

from django.test import TestCase
from django.urls import reverse

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import person, project


class ListFilterTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.group = ops.create_group(todolist=self.list.todolist, title="Later")
        self.todo("Ada's", [self.ada])
        self.todo("Bob's", [self.bob])
        self.todo("Nobody's", [])
        self.todo("Bob's grouped", [self.bob], group=self.group)
        self.todo("Ada's grouped", [self.ada], group=self.group)
        done = self.todo("Bob's done", [self.bob])
        ops.complete(done, actor=self.ada)
        done = self.todo("Ada's done", [self.ada])
        ops.complete(done, actor=self.ada)

    def todo(self, title, assignees, group=None):
        return ops.create_todo(
            todolist=self.list,
            title=title,
            creator=self.ada,
            group=group,
            assignees=assignees,
        )

    def page(self, user, **query):
        self.client.force_login(user)
        return self.client.get(self.list.get_absolute_url(), query)

    def shown(self, response):
        ids = [
            int(pk)
            for pk in re.findall(r'data-todo="(\d+)"', response.content.decode())
        ]
        return set(Item.objects.filter(pk__in=ids).values_list("title", flat=True))

    def test_anybody_by_default(self):
        response = self.page(self.ada)
        self.assertEqual(
            self.shown(response),
            {
                "Ada's",
                "Bob's",
                "Nobody's",
                "Bob's grouped",
                "Ada's grouped",
                "Bob's done",
                "Ada's done",
            },
        )
        self.assertEqual(response.context["filtered"], 0)
        self.assertNotContains(response, 'id="list-filtered"')

    def test_a_person(self):
        response = self.page(self.ada, assignee=self.bob.pk)
        self.assertEqual(self.shown(response), {"Bob's", "Bob's grouped", "Bob's done"})
        self.assertEqual(response.context["completed_count"], 1)
        # The groups stay, so the board keeps its columns
        self.assertContains(response, f'id="group-{self.group.pk}"')
        self.assertContains(response, 'id="list-filtered"')
        self.assertContains(response, "Assigned to: Bob")
        self.assertEqual(response.context["filtered"], 1)

    def test_me_and_nobody(self):
        self.assertEqual(
            self.shown(self.page(self.bob, assignee="me")),
            {"Bob's", "Bob's grouped", "Bob's done"},
        )
        self.assertEqual(
            self.shown(self.page(self.ada, assignee="nobody")), {"Nobody's"}
        )

    def test_the_default_spelled_out(self):
        response = self.page(self.ada, assignee="anybody")
        self.assertEqual(len(self.shown(response)), 7)
        self.assertEqual(response.context["filtered"], 0)

    def test_unknown_values_show_an_error_and_no_todos(self):
        response = self.page(self.ada, assignee="x")
        self.assertEqual(self.shown(response), set())
        self.assertContains(response, 'class="text-danger"')

    def test_nothing_matches(self):
        other = person("Dora")
        self.project.memberships.create(user=other)
        response = self.page(self.ada, assignee=other.pk)
        self.assertContains(response, "No to-dos match the filter.")
        self.assertNotContains(self.page(self.ada), "No to-dos match the filter.")

    def test_clients_choose_among_anybody_me_and_nobody(self):
        response = self.page(self.cleo)
        choices = [
            c[0] for c in response.context["filter_form"].fields["assignee"].choices
        ]
        self.assertEqual(choices, ["", "me", "nobody"])
        response = self.page(self.cleo, assignee=self.bob.pk)
        self.assertEqual(self.shown(response), set())

    def test_staff_choose_among_the_members(self):
        outsider = person("Eve")
        response = self.page(self.ada)
        choices = dict(response.context["filter_form"].fields["assignee"].choices)
        self.assertIn(str(self.bob.pk), choices)
        self.assertNotIn(str(outsider.pk), choices)

    def test_links_keep_the_filter_and_the_view(self):
        response = self.page(self.ada, assignee=self.bob.pk, view="board")
        self.assertContains(response, f'href="?view=list&amp;assignee={self.bob.pk}"')
        self.assertContains(response, '<input type="hidden" name="view" value="board">')
        # Completing comes back to the filtered page
        self.assertContains(
            response,
            f'name="next"\n      value="{self.list.get_absolute_url()}'
            f'?view=board&amp;assignee={self.bob.pk}"',
        )

    def test_completing_returns_to_the_filtered_page(self):
        self.client.force_login(self.ada)
        todo = Item.objects.get(title="Bob's")
        back = f"{self.list.get_absolute_url()}?assignee={self.bob.pk}"
        response = self.client.post(
            reverse("todo_toggle", args=[todo.pk]), {"done": "1", "next": back}
        )
        self.assertRedirects(response, back, fetch_redirect_response=False)

    def test_show_more_keeps_the_filter(self):
        for i in range(10):
            done = self.todo(f"Bob's old {i}", [self.bob])
            ops.complete(done, actor=self.ada)
            done = self.todo(f"Ada's old {i}", [self.ada])
            ops.complete(done, actor=self.ada)
        response = self.page(self.ada, assignee=self.bob.pk)
        self.assertEqual(response.context["completed_count"], 11)
        self.assertIn(f"assignee={self.bob.pk}", response.context["more_url"])
        fragment = response.context["more_fragment_url"]
        self.assertIn(f"assignee={self.bob.pk}", fragment)
        rows = self.shown(self.client.get(fragment))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(title.startswith("Bob's") for title in rows))

    def test_the_fragment_refuses_unknown_values(self):
        self.client.force_login(self.ada)
        url = reverse("list_completed", args=[self.list.pk])
        self.assertEqual(self.shown(self.client.get(url, {"assignee": "x"})), set())


class ListFilterAPITest(TestCase):
    """``assignee`` on a list's to-dos, open and completed"""

    setUp = ListFilterTest.setUp
    todo = ListFilterTest.todo

    def api(self, user, path="", **params):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return self.client.get(
            f"/api/v1/lists/{self.list.pk}/todos/{path}",
            params,
            headers={"authorization": f"Bearer {secret}"},
        )

    def titles(self, response):
        data = response.json()
        rows = data["results"] if isinstance(data, dict) else data
        return {t["title"] for t in rows}

    def test_api(self):
        self.assertEqual(
            self.titles(self.api(self.ada, assignee=self.bob.pk)),
            {"Bob's", "Bob's grouped"},
        )
        self.assertEqual(
            self.titles(self.api(self.bob, "completed/", assignee="me")), {"Bob's done"}
        )
        self.assertEqual(
            self.titles(self.api(self.ada, assignee="nobody")), {"Nobody's"}
        )
        self.assertEqual(len(self.titles(self.api(self.ada, assignee="anybody"))), 5)
        self.assertEqual(self.api(self.ada, assignee="x").status_code, 400)


class DraggingNextToTest(TestCase):
    """In a filtered list the index among the to-dos shown isn't the index
    among all: dragging names the to-do shown above (or below)"""

    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        self.todos = {
            title: ops.create_todo(todolist=self.list, title=title, creator=self.ada)
            for title in "ABCDE"
        }

    def order(self):
        return "".join(
            Item.objects
            .filter(parent=self.list, todo__completed_at__isnull=True)
            .order_by("position", "pk")
            .values_list("title", flat=True)
        )

    def move(self, title, **data):
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("todos_move", args=[self.list.pk]),
            {"todos": self.todos[title].pk, "group": ""} | data,
        )
        self.assertEqual(response.status_code, 204)

    def test_after(self):
        # Shown: A, C, E; E dropped between A and C, the index among those
        # shown is 1
        self.move("E", index=1, after=self.todos["A"].pk)
        self.assertEqual(self.order(), "AEBCD")

    def test_before(self):
        # Shown: C, E; E dropped above C
        self.move("E", index=0, before=self.todos["C"].pk)
        self.assertEqual(self.order(), "ABECD")

    def test_the_index_without_neighbours(self):
        self.move("E", index=1)
        self.assertEqual(self.order(), "AEBCD")

    def test_a_neighbour_gone_falls_back_to_the_index(self):
        ops.complete(self.todos["A"], actor=self.ada)
        self.move("E", index=2, after=self.todos["A"].pk)
        self.assertEqual(self.order(), "BCED")
