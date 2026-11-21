from django.test import TestCase

from biwak.activity import feed
from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.reactions import operations
from biwak.test_utils import person, project


class FeedTest(TestCase):
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
        self.tent = ops.create_todo(
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        self.pegs = ops.create_todo(
            todolist=self.shared, title="Buy pegs", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret plan", creator=self.ada
        )

    def entries(self, user):
        events = feed.feed_events(user).filter(action=Action.REACTED)
        events = list(events)
        feed.attach(events, self.ada)
        return feed.merge(events)

    def test_one_line_per_person_and_item(self):
        operations.toggle_reaction(self.bob, "👍", item=self.tent)
        operations.toggle_reaction(self.bob, "🎉", item=self.tent)
        operations.toggle_reaction(self.bob, "Nice", item=self.pegs)
        entries = self.entries(self.ada)
        self.assertEqual([e.count for e in entries], [1, 2])
        self.assertEqual(entries[1].contents, ["👍", "🎉"])
        # Another person doesn't merge in
        operations.toggle_reaction(self.ada, "👍", item=self.pegs)
        self.assertEqual([e.count for e in self.entries(self.ada)], [1, 1, 2])

    def test_page(self):
        operations.toggle_reaction(self.bob, "👍", item=self.tent)
        operations.toggle_reaction(self.bob, "🎉", item=self.tent)
        operations.toggle_reaction(self.bob, "Thanks!", item=self.pegs)
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "reacted to")
        self.assertContains(response, "👍 🎉")
        self.assertContains(response, "Thanks!")
        self.assertContains(response, "Order the tent")

    def test_comment_reaction_in_the_feed(self):
        comment = ops.add_comment(self.tent, author=self.ada, content="Hi")
        operations.toggle_reaction(self.bob, "🔥", comment=comment)
        self.client.force_login(self.bob)
        self.assertContains(self.client.get("/feed/"), "a comment on")

    def test_client_doesnt_see_internal_reactions(self):
        operations.toggle_reaction(self.bob, "🤫", item=self.secret)
        operations.toggle_reaction(self.bob, "👍", item=self.tent)
        self.assertEqual(len(self.entries(self.cleo)), 1)
        self.client.force_login(self.cleo)
        for url in ["/feed/", f"/projects/{self.project.pk}/feed/"]:
            response = self.client.get(url)
            self.assertNotContains(response, "Secret plan")
            self.assertNotContains(response, "🤫")
            self.assertContains(response, "👍")
        api = self.client.get("/api/v1/feed/").json()
        self.assertEqual(
            [e["data"]["content"] for e in api["results"] if e["action"] == "reacted"],
            ["👍"],
        )

    def test_not_on_the_projects_page(self):
        operations.toggle_reaction(self.bob, "👍", item=self.tent)
        self.assertTrue(Event.objects.filter(action=Action.REACTED).exists())
        self.client.force_login(self.ada)
        response = self.client.get(self.project.get_absolute_url())
        self.assertNotContains(response, "reacted")
