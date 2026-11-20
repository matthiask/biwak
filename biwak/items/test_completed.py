import datetime as dt
import re
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from biwak.items import operations as ops
from biwak.items.models import Item, Status
from biwak.test_utils import person, project


class CompletedTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )

    def complete(self, count, *, same_time=False):
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        for i in range(count):
            todo = ops.create_todo(
                todolist=self.list, title=f"Done {i:03}", creator=self.ada
            )
            ops.complete(todo, actor=self.ada)
            stamp = base if same_time else base + dt.timedelta(minutes=i)
            Item.objects.filter(pk=todo.pk).update(updated_at=stamp)
            todo.todo.__class__.objects.filter(pk=todo.pk).update(completed_at=stamp)

    def titles(self, response):
        return re.findall(r"Done \d{3}", response.content.decode())

    def page(self, user, **query):
        self.client.force_login(user)
        return self.client.get(reverse("list", args=[self.list.pk]), query)

    def test_count_and_first_page(self):
        self.complete(25)
        ops.create_todo(todolist=self.list, title="Open", creator=self.ada)
        response = self.page(self.ada)
        self.assertContains(response, "Completed (25)")
        titles = self.titles(response)
        self.assertEqual(len(titles), 20)
        self.assertEqual(titles[0], "Done 024")
        self.assertContains(response, "Show more")
        self.assertEqual(response.context["completed_count"], 25)

    def test_no_completed_no_section(self):
        response = self.page(self.ada)
        self.assertNotContains(response, "Completed (")

    def test_short_list_has_no_show_more(self):
        self.complete(20)
        response = self.page(self.ada)
        self.assertContains(response, "Completed (20)")
        self.assertNotContains(response, "Show more")

    def test_board_columns_have_no_completed(self):
        self.complete(3)
        response = self.page(self.ada, view="board")
        self.assertEqual(response.context["ungrouped"], [])
        self.assertContains(response, "Completed (3)")
        html = response.content.decode()
        columns = html[: html.index('class="mt-4 wb-completed"')]
        self.assertNotIn("Done 00", columns)

    def walk(self, user):
        """All titles from paging through, in order"""
        response = self.page(user)
        seen = self.titles(response)
        url = None
        while match := re.search(
            r'hx-get="(/lists/[^"]+/completed/[^"]+)"', response.content.decode()
        ):
            url = match.group(1).replace("&amp;", "&")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            seen += self.titles(response)
        return seen

    def check_paging(self, seen, total):
        self.assertEqual(len(seen), total)
        self.assertEqual(len(set(seen)), total)

    def test_paging_without_gaps(self):
        self.complete(120)
        seen = self.walk(self.ada)
        self.check_paging(seen, 120)
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_paging_with_equal_completed_at(self):
        self.complete(120, same_time=True)
        self.check_paging(self.walk(self.ada), 120)

    def test_fragment_sizes(self):
        self.complete(130)
        first = self.page(self.ada)
        cursor = re.search(r'before=([^"]+)"', first.content.decode()).group(1)
        url = reverse("list_completed", args=[self.list.pk])
        second = self.client.get(url, {"before": unquote(cursor)})
        # Not the whole page: no layout
        self.assertNotContains(second, "<html")
        self.assertEqual(len(self.titles(second)), 50)

    def test_bad_cursor(self):
        self.client.force_login(self.ada)
        url = reverse("list_completed", args=[self.list.pk])
        for bad in ["x", "1,x", "2026-01-01T00:00:00,3", "9" * 30 + ",1"]:
            self.assertEqual(self.client.get(url, {"before": bad}).status_code, 404)

    def test_trashed_not_counted(self):
        self.complete(3)
        Item.objects.filter(parent=self.list, title="Done 000").update(
            status=Status.TRASHED
        )
        self.assertContains(self.page(self.ada), "Completed (2)")

    def test_client_sees_visible_lists_only(self):
        self.complete(25)
        response = self.page(self.cleo)
        self.assertContains(response, "Completed (25)")
        self.assertEqual(len(self.walk(self.cleo)), 25)

    def test_client_gets_404_for_internal_list(self):
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        todo = ops.create_todo(todolist=internal, title="Secret", creator=self.ada)
        ops.complete(todo, actor=self.ada)
        self.client.force_login(self.cleo)
        for name in ["list", "list_completed"]:
            response = self.client.get(reverse(name, args=[internal.pk]))
            self.assertEqual(response.status_code, 404)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("list_completed", args=[internal.pk]))
        self.assertContains(response, "Secret")
