"""Externals (specs/access.md, specs/organizations.md): staff of an
organization other than the own one see only the projects
they're members of, through every entry point. Pia is an external and a
member of "Camp"; "Lodge" is all-access, without her; "Salaries" is
limited. In Camp she knows its people (decided 2026-11-21): the members
and the own staff, who open it as it's all-access; not Dora, a client of
Lodge, nor Pat, an external in no project."""

import json

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak import test_cli
from biwak.accounts.models import APIToken
from biwak.activity import mentions
from biwak.activity.mails import send_mails
from biwak.activity.models import Event, Notification
from biwak.activity.notify import can_see, who_can_see
from biwak.activity.operations import subscribe
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.organizations import operations as org_ops
from biwak.projects.models import Project
from biwak.test_utils import external, organization, person, project


class ExternalTestCase(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.ada = person("Ada", organization=self.own)
        self.bob = person("Bob")  # without an organization: the own staff too
        self.cleo = person("Cleo", client=True)
        self.pia = external("Pia")
        self.pat = external("Pat")  # an external in no project
        self.dora = person("Dora", client=True)  # a client of Lodge only
        self.camp = project("Camp", members=[self.ada, self.pia, self.cleo])
        self.lodge = project("Lodge", members=[self.ada, self.dora])
        self.salaries = project("Salaries", members=[self.ada], all_access=False)
        self.camp_list = ops.create_list(
            project=self.camp, title="Tents", creator=self.ada
        )
        self.camp_todo = ops.create_todo(
            todolist=self.camp_list, title="Pitch the tents", creator=self.ada
        )
        self.lodge_list = ops.create_list(
            project=self.lodge, title="Rooms", creator=self.ada
        )
        self.lodge_todo = ops.create_todo(
            todolist=self.lodge_list, title="Book the lodge", creator=self.ada
        )
        self.secret = ops.create_list(
            project=self.salaries, title="Payroll", creator=self.ada
        )


class QueriesTest(ExternalTestCase):
    def test_projects_and_items(self):
        accessible = Project.objects.accessible_to
        self.assertEqual(set(accessible(self.pia)), {self.camp})
        self.assertEqual(set(accessible(self.pat)), set())
        self.assertEqual(
            set(accessible(self.ada)), {self.camp, self.lodge, self.salaries}
        )
        self.assertEqual(set(accessible(self.bob)), {self.camp, self.lodge})
        self.assertEqual(
            set(Item.objects.visible_to(self.pia)), {self.camp_list, self.camp_todo}
        )
        # Internal items of their projects, unlike clients
        self.assertFalse(self.camp_list.is_client_visible)
        self.assertEqual(
            {e.project for e in Event.objects.visible_to(self.pia)}, {self.camp}
        )

    def test_who_can_see(self):
        self.assertEqual(set(who_can_see(self.lodge_todo)), {self.ada, self.bob})
        self.assertEqual(
            set(who_can_see(self.camp_todo)), {self.ada, self.bob, self.pia}
        )
        for user in [self.ada, self.bob, self.pia, self.pat, self.cleo]:
            for item in [self.camp_todo, self.lodge_todo, self.secret]:
                with self.subTest(user=user, item=item):
                    self.assertEqual(
                        can_see(user, item), user in set(who_can_see(item))
                    )

    def test_external_made_own_and_back(self):
        """An admin moving them in makes them see all-access projects"""
        root = person("Root", is_admin=True)
        org_ops.set_organization(self.pia, self.own, actor=root)
        self.assertIn(self.lodge, Project.objects.accessible_to(self.pia))
        # Without one, an individual: an external (decided 2026-11-21)
        org_ops.set_organization(self.pia, None, actor=root)
        self.assertTrue(self.pia.is_external)
        self.assertNotIn(self.lodge, Project.objects.accessible_to(self.pia))
        org_ops.set_organization(self.pia, organization("Other Agency"), actor=root)
        self.assertNotIn(self.lodge, Project.objects.accessible_to(self.pia))
        # Their organization merged into the own organization
        org_ops.merge(self.pia.organization, self.own, actor=root, confirmed=True)
        self.pia.refresh_from_db()
        self.assertIn(self.lodge, Project.objects.accessible_to(self.pia))

    def test_assignable_and_mentionable(self):
        """Externals are assigned and mentioned as members only; they assign
        and mention the project's people, like own staff, nobody else"""
        assignable = set(ops.assignable_people(self.camp_todo, self.ada))
        self.assertEqual(assignable, {self.ada, self.bob, self.pia})
        self.assertEqual(
            set(ops.assignable_people(self.camp_todo, self.pia)), assignable
        )
        self.assertNotIn(self.pia, set(ops.assignable_people(self.lodge_todo)))
        names = {
            p["name"]
            for p in mentions.candidates(self.camp_todo, "", for_user=self.pia)
        }
        self.assertEqual(
            names, {"Ada Example", "Bob Example", "Cleo Example", "Pia Example"}
        )
        names = {
            p["name"]
            for p in mentions.candidates(self.camp_todo, "", for_user=self.ada)
        }
        self.assertIn("Bob Example", names)
        self.assertIn("Pat Example", names)
        # Pia's @Bob resolves, Pat (in no project) and Dora (Lodge) stay
        # plain text
        text = mentions.resolve(
            self.camp_todo,
            "@bob@example.org @pat@example.org @dora@example.org @Ada",
            author=self.pia,
        )
        self.assertEqual(
            text,
            f"{mentions.syntax(self.bob)} @pat@example.org @dora@example.org"
            f" {mentions.syntax(self.ada)}",
        )

    def test_clients_still_know_members_only(self):
        names = {
            p["name"]
            for p in mentions.candidates(self.camp_todo, "", for_user=self.cleo)
        }
        self.assertEqual(names, {"Ada Example", "Cleo Example", "Pia Example"})
        self.assertEqual(
            self.camp.people_known_to(self.cleo, [self.bob, self.ada]), [self.ada]
        )
        self.assertEqual(
            self.camp.people_known_to(self.pia, [self.bob, self.ada, self.dora]),
            [self.bob, self.ada],
        )

    def test_mentions_by_externals_reach_the_project_s_people(self):
        # Bob is own staff, not a member: he sees Camp's internal to-do
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(
                self.camp_todo,
                author=self.pia,
                content=f"{mentions.syntax(self.bob)} {mentions.syntax(self.pat)}",
            )
        told = {n.user for n in Notification.objects.all()}
        self.assertIn(self.bob, told)
        self.assertNotIn(self.pat, told)


class PagesTest(ExternalTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.pia)

    def test_projects(self):
        response = self.client.get(reverse("projects"))
        self.assertContains(response, "Camp")
        self.assertNotContains(response, "Lodge")
        self.assertNotContains(response, "Salaries")
        self.assertNotContains(response, "New project")
        for url in [
            self.lodge.get_absolute_url(),
            self.lodge_todo.get_absolute_url(),
            self.lodge_list.get_absolute_url(),
            f"/projects/{self.lodge.pk}/people/",
            f"/projects/{self.lodge.pk}/feed/",
        ]:
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.post(f"/projects/{self.lodge.pk}/join/").status_code, 404
        )
        self.assertFalse(self.lodge.is_member(self.pia))
        for url in [
            self.camp.get_absolute_url(),
            self.camp_todo.get_absolute_url(),
            self.camp_list.get_absolute_url(),
        ]:
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_new_projects_or_members(self):
        """The forms offer people and organizations externals don't know"""
        self.assertEqual(self.client.get("/projects/new/").status_code, 403)
        people = f"/projects/{self.camp.pk}/people/"
        self.assertEqual(self.client.get(f"{people}add/").status_code, 403)
        self.assertEqual(self.client.get(f"{people}invite/").status_code, 403)
        response = self.client.get(people)
        self.assertNotContains(response, "Invite by email")
        # Nor remove themselves (decided 2026-11-22)
        self.assertNotContains(response, "/remove/")
        palette = self.client.get("/palette/").content.decode()
        self.assertNotIn("New project", palette)

    def test_feed(self):
        response = self.client.get("/feed/")
        self.assertContains(response, "Pitch the tents")
        self.assertNotContains(response, "Book the lodge")
        self.assertNotContains(response, "Payroll")
        # The person filter goes by projects shared as members, as for own
        # staff: Bob opens Camp without being a member
        for who in [self.bob, self.dora]:
            response = self.client.get("/feed/", {"person": who.pk})
            self.assertFalse(response.context["form"].is_valid())
        self.assertNotContains(
            self.client.get(f"/people/{self.bob.pk}/"), f"/feed/?person={self.bob.pk}"
        )

    def test_search_and_palette(self):
        response = self.client.get("/search/", {"q": "Book"})
        self.assertNotContains(response, self.lodge_todo.get_absolute_url())
        response = self.client.get("/search/", {"q": "Pitch"})
        self.assertContains(response, self.camp_todo.get_absolute_url())
        found = json.dumps(self.client.get("/palette/", {"q": "lodge"}).json())
        self.assertNotIn("Lodge", found)
        self.assertNotIn("Book the lodge", found)
        found = json.dumps(self.client.get("/palette/", {"q": "camp"}).json())
        self.assertIn("Camp", found)
        # People: only those sharing a project
        found = json.dumps(self.client.get("/palette/", {"q": "Bob"}).json())
        self.assertNotIn("Bob Example", found)
        # Own staff find them
        self.client.force_login(self.bob)
        response = self.client.get("/search/", {"q": "Book"})
        self.assertContains(response, self.lodge_todo.get_absolute_url())
        found = json.dumps(self.client.get("/palette/", {"q": "lodge"}).json())
        self.assertIn("Lodge", found)

    def test_mentionable(self):
        response = self.client.get(f"/items/{self.camp_todo.pk}/mentionable/")
        names = {p["name"] for p in response.json()}
        self.assertIn("Bob Example", names)
        self.assertNotIn("Pat Example", names)
        self.assertNotIn("Dora Example", names)
        self.assertEqual(
            self.client.get(f"/items/{self.lodge_todo.pk}/mentionable/").status_code,
            404,
        )
        self.client.force_login(self.ada)
        response = self.client.get(f"/items/{self.camp_todo.pk}/mentionable/?q=Pia")
        [pia] = response.json()
        self.assertEqual(pia["organization"], "Example External Agency")


class NotificationsTest(ExternalTestCase):
    def told(self, run):
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            run()
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }

    def test_lantern_and_mails(self):
        """Subscribed (e.g. before becoming an external) to an item of a
        project they're not in: neither the lantern nor mails tell them"""
        subscribe(self.pia, self.lodge_todo)
        subscribe(self.bob, self.lodge_todo)
        told = self.told(
            lambda: ops.add_comment(self.lodge_todo, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob})
        subscribe(self.pia, self.camp_todo)
        told = self.told(
            lambda: ops.add_comment(self.camp_todo, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.pia})
        self.client.force_login(self.pia)
        response = self.client.get("/lantern/")
        self.assertContains(response, "Pitch the tents")
        self.assertNotContains(response, "Book the lodge")
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + timezone.timedelta(minutes=11))
        to_pia = [m for m in mail.outbox if m.to == [self.pia.email]]
        self.assertEqual(len(to_pia), 1)
        self.assertIn("Pitch the tents", to_pia[0].subject)

    def test_mentions_dont_reach_externals_outside(self):
        mention = mentions.syntax(self.pia)
        told = self.told(
            lambda: ops.add_comment(
                self.lodge_todo, author=self.ada, content=f"{mention} look"
            )
        )
        self.assertNotIn(self.pia, told)
        told = self.told(
            lambda: ops.add_comment(
                self.camp_todo, author=self.ada, content=f"{mention} look"
            )
        )
        self.assertIn(self.pia, told)

    def test_names_mentioned_outside_the_members(self):
        """Pia reads Bob's mention (own staff with access) with his name,
        Pat's (in no project) as the label written; Cleo, a client, both as
        written"""
        text = f"[@Somebody](person:{self.bob.pk}) [@Else](person:{self.pat.pk})"
        for reader, expected in [
            (self.pia, "@Bob @Else"),
            (self.cleo, "@Somebody @Else"),
            (self.ada, "@Bob @Else"),
        ]:
            with self.subTest(reader=reader), mentions.reading_as(reader):
                self.assertEqual(mentions.plain(text, self.camp_todo), expected)


class APITest(ExternalTestCase):
    def setUp(self):
        super().setUp()
        _token, secret = APIToken.create_for(user=self.pia, title="T", access="write")
        self.headers = {"authorization": f"Bearer {secret}"}

    def get(self, path, **params):
        return self.client.get(f"/api/v1/{path}", params, headers=self.headers)

    def test_projects_and_items(self):
        names = {p["name"] for p in self.get("projects/").json()}
        self.assertEqual(names, {"Camp"})
        self.assertEqual(self.get(f"todos/{self.lodge_todo.pk}/").status_code, 404)
        self.assertEqual(self.get(f"lists/{self.lodge_list.pk}/").status_code, 404)
        self.assertEqual(self.get(f"todos/{self.camp_todo.pk}/").status_code, 200)
        self.assertEqual(self.get(f"projects/{self.lodge.pk}/feed/").status_code, 404)
        feed = json.dumps(self.get("feed/").json())
        self.assertNotIn("Book the lodge", feed)
        found = json.dumps(self.get("search/", q="lodge").json())
        self.assertNotIn("Book the lodge", found)
        response = self.client.post(
            f"/api/v1/projects/{self.lodge.pk}/join/", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            "/api/v1/projects/",
            {"name": "Mine"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_people(self):
        """The person's organization and whether they're an external"""
        member = next(
            m
            for m in self.get(f"projects/{self.camp.pk}/members/").json()
            if m["id"] == self.pia.pk
        )
        self.assertEqual(member["organization"], "Example External Agency")
        self.assertEqual(member["organization_id"], self.pia.organization_id)

    def send(self, method, path, data):
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers=self.headers,
        )

    def test_the_project_s_people(self):
        """Pia assigns, subscribes and mentions Bob (own staff, not a
        member) and sees him named; Dora (another project) and an ID nobody
        has get the same answer"""
        todo = f"todos/{self.camp_todo.pk}/"
        response = self.send("patch", todo, {"assignees": [self.bob.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([a["id"] for a in response.json()["assignees"]], [self.bob.pk])
        dora = self.send("patch", todo, {"assignees": [self.dora.pk]})
        nobody = self.send("patch", todo, {"assignees": [999999]})
        self.assertEqual(dora.status_code, 400)
        self.assertEqual(dora.json(), nobody.json())
        self.assertNotIn("Dora", dora.content.decode())
        subscribers = f"items/{self.camp_todo.pk}/subscribers/"
        response = self.send("post", subscribers, {"people": [self.ada.pk]})
        self.assertEqual(response.status_code, 200)
        names = {
            s["person"]["name"] for s in self.get(subscribers).json()["subscribers"]
        }
        self.assertIn("Bob Example", names)
        dora = self.send("post", subscribers, {"people": [self.dora.pk]})
        nobody = self.send("post", subscribers, {"people": [999999]})
        self.assertEqual(dora.status_code, 400)
        self.assertEqual(dora.json(), nobody.json())
        response = self.send(
            "post",
            f"items/{self.camp_todo.pk}/comments/",
            {"content": "@bob@example.org @dora@example.org look"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        html = response.json()["content_html"]
        self.assertIn("@Bob", html)
        self.assertIn("@dora@example.org", html)

    def test_clients_still_learn_about_members_only(self):
        shared = ops.create_list(
            project=self.camp, title="Shared", creator=self.ada, visible=True
        )
        todo = ops.create_todo(todolist=shared, title="Shared", creator=self.ada)
        subscribe(self.bob, todo)
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="write")
        response = self.client.get(
            f"/api/v1/items/{todo.pk}/subscribers/",
            headers={"authorization": f"Bearer {secret}"},
        )
        names = {s["person"]["name"] for s in response.json()["subscribers"]}
        self.assertEqual(names, {"Ada Example"})


class CLITest(test_cli.CLITest):
    def test_externals_assign_the_project_s_people(self):
        """Ada, an external now, assigns Bob (own staff with access to the
        all-access project) by ID, not Dora of another project"""
        bob = person("Bob")
        dora = person("Dora", client=True)
        project("Lodge", members=[dora])
        org_ops.set_organization(
            self.ada,
            organization("Example External Agency"),
            actor=person("Root", is_admin=True),
        )
        result = self.biwak(
            "todo", "add", self.list.pk, "Pitch", "--assign", bob.pk, "--json"
        )
        self.assertEqual(result.exit_code, 0, result.output)
        todo = json.loads(result.stdout)
        self.assertEqual([a["name"] for a in todo["assignees"]], ["Bob Example"])
        result = self.biwak("todo", "add", self.list.pk, "Pack", "--assign", dora.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn("Dora", result.output)

    def test_projects(self):
        lodge = project("Lodge")
        org_ops.set_organization(
            self.ada,
            organization("Example External Agency"),
            actor=person("Root", is_admin=True),
        )
        names = {p["name"] for p in json.loads(self.biwak("projects", "--json").stdout)}
        self.assertEqual(names, {"Website"})
        result = self.biwak("project", "join", lodge.pk)
        self.assertEqual(result.exit_code, 1)
