import datetime as dt
import re
from unittest.mock import patch
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse

from biwak.items import operations as ops, views
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
        """The latest few shown at once, no collapsible (decided
        2026-11-23)"""
        self.complete(25)
        ops.create_todo(todolist=self.list, title="Open", creator=self.ada)
        response = self.page(self.ada)
        self.assertContains(response, "Completed (25)")
        self.assertNotContains(response, '<details class="mt-4 wb-completed')
        titles = self.titles(response)
        self.assertEqual(len(titles), views.COMPLETED_FIRST)
        self.assertEqual(titles[0], "Done 024")
        self.assertContains(response, "Show more")
        self.assertEqual(response.context["completed_count"], 25)

    def test_show_more_without_javascript(self):
        """The link is the page with more of them; htmx puts it into the
        address bar, so reloading (and live updates) keep them"""
        self.complete(40)
        response = self.page(self.ada)
        url = f"{self.list.get_absolute_url()}?completed={5 + 25}"
        self.assertContains(response, f'href="{url}#completed"')
        self.assertContains(response, f'hx-replace-url="{url}"')
        response = self.page(self.ada, completed=30)
        self.assertEqual(len(self.titles(response)), 30)
        self.assertContains(response, f"?completed={30 + 25}#completed")
        response = self.page(self.ada, completed=55)
        self.assertEqual(len(self.titles(response)), 40)
        self.assertNotContains(response, "Show more")
        # Nonsense is the default, never fewer
        for value in ["x", "-3", "1", ""]:
            with self.subTest(value=value):
                response = self.page(self.ada, completed=value)
                self.assertEqual(len(self.titles(response)), 5)

    def test_show_more_keeps_the_view(self):
        self.complete(8)
        response = self.page(self.ada, view="board")
        self.assertContains(response, "?view=board&amp;completed=30#completed")
        match = re.search(
            r'hx-get="(/lists/[^"]+/completed/[^"]+)"', response.content.decode()
        )
        more = self.client.get(match.group(1).replace("&amp;", "&"))
        self.assertEqual(len(self.titles(more)), 3)
        self.assertNotContains(more, "Show more")

    @patch.object(views, "COMPLETED_FIRST", 2)
    @patch.object(views, "COMPLETED_MORE", 3)
    def test_the_fragment_links_to_the_page_showing_as_many(self):
        self.complete(10)
        response = self.page(self.ada)
        match = re.search(
            r'hx-get="(/lists/[^"]+/completed/[^"]+)"', response.content.decode()
        )
        more = self.client.get(match.group(1).replace("&amp;", "&"))
        self.assertEqual(len(self.titles(more)), 3)
        # 2 + 3 shown now: the next link shows 8
        self.assertContains(
            more, f'href="{self.list.get_absolute_url()}?completed=8#completed"'
        )

    def test_no_completed_no_section(self):
        response = self.page(self.ada)
        self.assertNotContains(response, "Completed (")

    def test_completed_to_dos_have_no_drag_handles(self):
        """Nothing sorts the completed section, open to-dos keep theirs"""
        self.complete(2)
        ops.create_todo(todolist=self.list, title="Open", creator=self.ada)
        html = self.page(self.ada).content.decode()
        self.assertEqual(html.count("data-handle"), 1)
        # Also the pages "Show more" loads
        self.client.force_login(self.ada)
        more = self.client.get(reverse("list_completed", args=[self.list.pk]))
        self.assertNotContains(more, "data-handle")
        self.assertContains(more, "Done 001")

    def test_short_list_has_no_show_more(self):
        self.complete(5)
        response = self.page(self.ada)
        self.assertContains(response, "Completed (5)")
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

    # Small pages: the paging doesn't depend on their size
    @patch.object(views, "COMPLETED_FIRST", 5)
    @patch.object(views, "COMPLETED_MORE", 4)
    def test_paging_without_gaps(self):
        self.complete(12)
        seen = self.walk(self.ada)
        self.check_paging(seen, 12)
        self.assertEqual(seen, sorted(seen, reverse=True))

    @patch.object(views, "COMPLETED_FIRST", 5)
    @patch.object(views, "COMPLETED_MORE", 4)
    def test_paging_with_equal_completed_at(self):
        self.complete(12, same_time=True)
        self.check_paging(self.walk(self.ada), 12)

    @patch.object(views, "COMPLETED_FIRST", 5)
    @patch.object(views, "COMPLETED_MORE", 4)
    def test_fragment_sizes(self):
        self.complete(10)
        first = self.page(self.ada)
        self.assertEqual(len(self.titles(first)), 5)
        cursor = re.search(r'before=([^&"]+)', first.content.decode()).group(1)
        url = reverse("list_completed", args=[self.list.pk])
        second = self.client.get(url, {"before": unquote(cursor)})
        # Not the whole page: no layout
        self.assertNotContains(second, "<html")
        self.assertEqual(len(self.titles(second)), 4)

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
        self.assertEqual(len(self.titles(self.page(self.cleo, completed=30))), 25)

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
