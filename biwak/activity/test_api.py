import datetime as dt
from urllib.parse import parse_qs, urlsplit

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.activity.test_feed import FeedBase, event_at
from biwak.test_utils import person, project


class FeedAPITest(FeedBase):
    def api(self, user, access="read"):
        _token, secret = APIToken.create_for(user=user, title="T", access=access)
        return {"authorization": f"Bearer {secret}"}

    def get(self, user, path, **params):
        return self.client.get(f"/api/v1/{path}", params, headers=self.api(user))

    def test_feed_as_staff_and_as_client(self):
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.secret,
        )
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.todo,
        )
        record(
            actor=self.ada,
            action=Action.MOVED,
            project=self.project,
            item=self.todo,
            to="Internal plans",
        )
        record(actor=self.ada, action=Action.JOINED, project=self.project)
        results = self.get(self.ada, "feed/").json()["results"]
        self.assertEqual(
            [(e["action"], e["item"]["title"] if e["item"] else None) for e in results],
            [
                ("joined", None),
                ("moved", "Open point"),
                ("completed", "Open point"),
                ("completed", "Secret"),
            ],
        )
        self.assertEqual(
            [e["visible_to_clients"] for e in results], [False, True, True, False]
        )
        self.assertEqual(results[1]["data"]["to"], "Internal plans")

        results = self.get(self.cleo, "feed/").json()["results"]
        self.assertEqual([e["action"] for e in results], ["moved", "completed"])
        self.assertTrue(all(e["visible_to_clients"] for e in results))
        self.assertNotIn("to", results[0]["data"])
        self.assertNotIn("Secret", str(results))

    def test_filters_and_scopes(self):
        other = project("Other", members=[self.ada, self.bob])
        item = ops_list(other, self.bob)
        Event.objects.all().delete()
        record(actor=self.bob, action=Action.EDITED, project=other, item=item)
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.todo,
        )

        def actions(path, **params):
            return [
                e["action"]
                for e in self.get(self.ada, path, **params).json()["results"]
            ]

        self.assertEqual(actions("feed/", project_id=other.pk), ["edited"])
        self.assertEqual(actions(f"projects/{other.pk}/feed/"), ["edited"])
        self.assertEqual(actions("feed/", person_id=self.bob.pk), ["edited"])
        self.assertEqual(actions(f"people/{self.bob.pk}/feed/"), ["edited"])
        self.assertEqual(actions("feed/", action="completed"), ["completed"])
        self.assertEqual(actions("feed/", kind="list"), ["edited"])
        self.assertEqual(actions("feed/", visible_to_clients="true"), ["completed"])
        self.assertEqual(actions("feed/", since="2999-01-01"), [])
        self.assertEqual(self.get(self.ada, "feed/", kind="nope").status_code, 422)

    def test_project_and_person_feeds_take_the_other_filter(self):
        other = project("Other", members=[self.ada, self.bob])
        item = ops_list(other, self.bob)
        Event.objects.all().delete()
        record(actor=self.bob, action=Action.EDITED, project=other, item=item)
        record(actor=self.ada, action=Action.COMPLETED, project=other, item=item)
        record(
            actor=self.bob,
            action=Action.COMPLETED,
            project=self.project,
            item=self.todo,
        )

        def actors(path, **params):
            return [
                (e["actor"]["id"], e["action"])
                for e in self.get(self.ada, path, **params).json()["results"]
            ]

        self.assertEqual(
            actors(f"projects/{other.pk}/feed/", person_id=self.bob.pk),
            [(self.bob.pk, "edited")],
        )
        self.assertEqual(
            actors(f"people/{self.bob.pk}/feed/", project_id=other.pk),
            [(self.bob.pk, "edited")],
        )
        # Someone not in the project, or a hidden project: 404 as on feed/
        stranger = person("Dora")
        for path, params in [
            (f"projects/{other.pk}/feed/", {"person_id": stranger.pk}),
            (f"people/{self.bob.pk}/feed/", {"project_id": project("Y").pk}),
        ]:
            self.assertEqual(self.get(self.ada, path, **params).status_code, 404)

    def test_no_access_is_404(self):
        hidden = project("Hidden", members=[self.bob], all_access=False)
        stranger = person("Dora")
        self.assertEqual(
            self.get(self.ada, f"projects/{hidden.pk}/feed/").status_code, 404
        )
        self.assertEqual(
            self.get(self.ada, "feed/", project_id=hidden.pk).status_code, 404
        )
        self.assertEqual(
            self.get(self.cleo, f"projects/{self.project.pk}/feed/").status_code, 200
        )
        self.assertEqual(
            self.get(self.ada, f"people/{stranger.pk}/feed/").status_code, 404
        )
        self.assertEqual(
            self.get(self.ada, "feed/", person_id=stranger.pk).status_code, 404
        )
        self.assertEqual(self.client.get("/api/v1/feed/").status_code, 401)

    def test_cursor_pagination(self):
        now = dt.datetime(2026, 11, 20, 12, tzinfo=dt.UTC)
        for n in range(5):
            event_at(self.ada, Action.EDITED, self.todo, now - dt.timedelta(minutes=n))
        first = self.get(self.ada, "feed/", page_size=2)
        first = first.json()
        self.assertEqual(len(first["results"]), 2)
        self.assertIsNone(first["previous"])
        seen = [e["id"] for e in first["results"]]
        cursor = cursor_of(first["next"])
        while cursor:
            page = self.get(self.ada, "feed/", page_size=2, cursor=cursor).json()
            seen += [e["id"] for e in page["results"]]
            cursor = cursor_of(page["next"])
        self.assertEqual(seen, list(Event.objects.values_list("pk", flat=True)))


def cursor_of(url):
    return parse_qs(urlsplit(url).query)["cursor"][0] if url else None


def ops_list(project, creator):
    from biwak.items import operations as ops

    return ops.create_list(project=project, title="Elsewhere", creator=creator)
