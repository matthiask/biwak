"""Partners (specs/access.md, specs/organizations.md): staff of an
organization other than the own one see only the projects
they're members of, through every entry point. Pia is a partner and a
member of "Camp"; "Lodge" is all-access, without her; "Salaries" is
limited."""

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
from biwak.test_utils import organization, partner, person, project


class PartnerTestCase(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.ada = person("Ada", organization=self.own)
        self.bob = person("Bob")  # without an organization: the own staff too
        self.cleo = person("Cleo", client=True)
        self.pia = partner("Pia")
        self.pat = partner("Pat")  # a partner in no project
        self.camp = project("Camp", members=[self.ada, self.pia, self.cleo])
        self.lodge = project("Lodge", members=[self.ada])
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


class QueriesTest(PartnerTestCase):
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

    def test_partner_made_own_and_back(self):
        """An admin moving them in makes them see all-access projects"""
        root = person("Root", is_admin=True)
        org_ops.set_organization(self.pia, self.own, actor=root)
        self.assertIn(self.lodge, Project.objects.accessible_to(self.pia))
        # Without one, an individual: a partner (decided 2026-11-21)
        org_ops.set_organization(self.pia, None, actor=root)
        self.assertTrue(self.pia.is_partner)
        self.assertNotIn(self.lodge, Project.objects.accessible_to(self.pia))
        org_ops.set_organization(self.pia, organization("Other Agency"), actor=root)
        self.assertNotIn(self.lodge, Project.objects.accessible_to(self.pia))
        # Their organization merged into the own organization
        org_ops.merge(self.pia.organization, self.own, actor=root, confirmed=True)
        self.pia.refresh_from_db()
        self.assertIn(self.lodge, Project.objects.accessible_to(self.pia))

    def test_assignable_and_mentionable(self):
        """Partners are assigned and mentioned as members only, and assign
        and mention members only (like clients, they don't learn about the
        others)"""
        assignable = set(ops.assignable_people(self.camp_todo, self.ada))
        self.assertEqual(assignable, {self.ada, self.bob, self.pia})
        self.assertEqual(
            set(ops.assignable_people(self.camp_todo, self.pia)), {self.ada, self.pia}
        )
        self.assertNotIn(self.pia, set(ops.assignable_people(self.lodge_todo)))
        names = {
            p["name"]
            for p in mentions.candidates(self.camp_todo, "", for_user=self.pia)
        }
        self.assertEqual(names, {"Ada Example", "Cleo Example", "Pia Example"})
        names = {
            p["name"]
            for p in mentions.candidates(self.camp_todo, "", for_user=self.ada)
        }
        self.assertIn("Bob Example", names)
        # Pia's @Bob stays plain text
        text = mentions.resolve(
            self.camp_todo, "@bob@example.org @Ada", author=self.pia
        )
        self.assertEqual(text, f"@bob@example.org {mentions.syntax(self.ada)}")


class PagesTest(PartnerTestCase):
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
        """The forms offer people and organizations partners don't know"""
        self.assertEqual(self.client.get("/projects/new/").status_code, 403)
        people = f"/projects/{self.camp.pk}/people/"
        self.assertEqual(self.client.get(f"{people}add/").status_code, 403)
        self.assertEqual(self.client.get(f"{people}invite/").status_code, 403)
        response = self.client.get(people)
        self.assertNotContains(response, "Invite by email")
        self.assertContains(response, "Leave")
        palette = self.client.get("/palette/").content.decode()
        self.assertNotIn("New project", palette)

    def test_feed(self):
        response = self.client.get("/feed/")
        self.assertContains(response, "Pitch the tents")
        self.assertNotContains(response, "Book the lodge")
        self.assertNotContains(response, "Payroll")
        # Bob shares no project with Pia
        self.assertEqual(
            self.client.get(f"/people/{self.bob.pk}/feed/").status_code, 404
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
        self.assertNotIn("Bob Example", names)
        self.assertEqual(
            self.client.get(f"/items/{self.lodge_todo.pk}/mentionable/").status_code,
            404,
        )
        self.client.force_login(self.ada)
        response = self.client.get(f"/items/{self.camp_todo.pk}/mentionable/?q=Pia")
        [pia] = response.json()
        self.assertEqual(pia["organization"], "Example Partner Agency")


class NotificationsTest(PartnerTestCase):
    def told(self, run):
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            run()
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }

    def test_lantern_and_mails(self):
        """Subscribed (e.g. before becoming a partner) to an item of a
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
            send_mails(now=timezone.now() + timezone.timedelta(minutes=3))
        to_pia = [m for m in mail.outbox if m.to == [self.pia.email]]
        self.assertEqual(len(to_pia), 1)
        self.assertIn("Pitch the tents", to_pia[0].subject)

    def test_mentions_dont_reach_partners_outside(self):
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
        """Pia reads Bob's mention as the label written"""
        ops.add_comment(
            self.camp_todo,
            author=self.ada,
            content=f"[@Somebody](person:{self.bob.pk}) knows",
        )
        with mentions.reading_as(self.pia):
            self.assertEqual(
                mentions.plain(f"[@Somebody](person:{self.bob.pk})", self.camp_todo),
                "@Somebody",
            )
        with mentions.reading_as(self.ada):
            self.assertEqual(
                mentions.plain(f"[@Somebody](person:{self.bob.pk})", self.camp_todo),
                "@Bob",
            )


class APITest(PartnerTestCase):
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
        """The person's organization and whether they're a partner"""
        member = next(
            m
            for m in self.get(f"projects/{self.camp.pk}/members/").json()
            if m["id"] == self.pia.pk
        )
        self.assertEqual(member["organization"], "Example Partner Agency")
        self.assertEqual(member["organization_id"], self.pia.organization_id)


class CLITest(test_cli.CLITest):
    def test_projects(self):
        lodge = project("Lodge")
        org_ops.set_organization(
            self.ada,
            organization("Example Partner Agency"),
            actor=person("Root", is_admin=True),
        )
        names = {p["name"] for p in json.loads(self.biwak("projects", "--json").stdout)}
        self.assertEqual(names, {"Website"})
        result = self.biwak("project", "join", lodge.pk)
        self.assertEqual(result.exit_code, 1)
