"""Using a team (specs/teams.md): what the people picker (``data-teams``)
and the ``@`` list (the mentionable endpoints' JSON) offer, for staff only:
the members who can be there, how many are left out and why; only people
are stored"""

import html
import json
import re

from django.test import TestCase
from django.urls import reverse

from biwak.activity.models import Subscription
from biwak.activity.operations import subscribe
from biwak.items import operations as ops
from biwak.teams import operations as team_ops
from biwak.test_utils import external, person, project


def picker_teams(response):
    """The ``data-teams`` of the first picker on the page"""
    match = re.search(r'data-teams="([^"]*)"', response.content.decode())
    return json.loads(html.unescape(match[1])) if match else None


def picker_groups(response):
    """The ``data-project-groups`` of the first picker on the page"""
    match = re.search(r'data-project-groups="([^"]*)"', response.content.decode())
    return json.loads(html.unescape(match[1])) if match else None


def ids(group):
    return [member["id"] for member in group["members"]]


def reasons(team):
    return {member["id"]: member["reason"] for member in team["members"]}


class Base(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")  # Staff, not a member
        self.cleo = person("Cleo", client=True)
        self.dora = person("Dora", client=True, organization="Other Client Ltd")
        self.ian = person("Ian", is_active=False)
        self.pia = external("Pia")
        self.project = project(members=[self.ada, self.cleo, self.ian, self.pia])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.internal, title="Plan", creator=self.ada
        )
        self.team = team_ops.create_team(
            name="Design team",
            members=[self.ada, self.bob, self.cleo, self.dora, self.ian],
            actor=self.ada,
        )


class MentionsTest(Base):
    def mentionable(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def teams(self, user, url):
        return [entry for entry in self.mentionable(user, url) if entry.get("team")]

    def test_staff_get_the_members_who_can_see_it(self):
        url = reverse("mentionable", args=[self.todo.pk]) + "?q=design"
        entries = self.mentionable(self.ada, url)
        [team] = [entry for entry in entries if entry.get("team")]
        self.assertEqual(team["name"], "Design team")
        self.assertTrue(team["available"])
        # Bob sees the all-access project's internal items, Cleo doesn't,
        # Dora isn't a member, Ian is inactive
        self.assertEqual(
            [member["id"] for member in team["members"]], [self.ada.pk, self.bob.pk]
        )
        self.assertEqual(team["members"][0]["short_name"], "Ada")
        self.assertEqual(
            team["detail"],
            "2 of 5: 1 can't see internal items, 1 not a member of this project,"
            " 1 inactive",
        )

    def test_teams_come_after_the_people(self):
        """Decided 2026-11-22: teams are a special case; not counted in
        the 10 people"""
        for index in range(12):
            person(f"Eve{index}")
        entries = self.mentionable(
            self.ada, reverse("mentionable", args=[self.todo.pk])
        )
        self.assertEqual(len(entries), 11)
        self.assertEqual(
            [bool(entry.get("team")) for entry in entries], [False] * 10 + [True]
        )

    def test_on_a_visible_item(self):
        todo = ops.create_todo(todolist=self.shared, title="Review", creator=self.ada)
        [team] = self.teams(self.ada, reverse("mentionable", args=[todo.pk]))
        self.assertEqual(
            [member["id"] for member in team["members"]],
            [self.ada.pk, self.bob.pk, self.cleo.pk],
        )
        self.assertEqual(
            team["detail"], "3 of 5: 1 not a member of this project, 1 inactive"
        )

    def test_everybody_can_be_mentioned(self):
        self.team.memberships.exclude(user__in=[self.ada, self.bob]).delete()
        [team] = self.teams(self.ada, reverse("mentionable", args=[self.todo.pk]))
        self.assertEqual(team["detail"], "2 members")

    def test_nobody_can_be_mentioned(self):
        team_ops.update_team(self.team, members=[self.dora, self.ian], actor=self.ada)
        [team] = self.teams(self.ada, reverse("mentionable", args=[self.todo.pk]))
        self.assertFalse(team["available"])
        self.assertEqual(team["members"], [])

    def test_the_query_finds_teams_by_name(self):
        url = reverse("mentionable", args=[self.todo.pk])
        self.assertEqual(self.teams(self.ada, url + "?q=Ada"), [])
        self.assertEqual(len(self.teams(self.ada, url + "?q=team+des")), 1)

    def test_new_items_and_new_to_dos(self):
        url = reverse("mentionable_new", args=[self.project.pk])
        [team] = self.teams(self.ada, url)
        self.assertNotIn(self.cleo.pk, [m["id"] for m in team["members"]])
        [team] = self.teams(self.ada, url + "?visible=1")
        self.assertIn(self.cleo.pk, [m["id"] for m in team["members"]])
        [team] = self.teams(
            self.ada, reverse("mentionable_list", args=[self.shared.pk])
        )
        self.assertIn(self.cleo.pk, [m["id"] for m in team["members"]])

    def test_clients_never_see_teams(self):
        todo = ops.create_todo(todolist=self.shared, title="Review", creator=self.ada)
        for url in (
            reverse("mentionable", args=[todo.pk]) + "?q=design",
            reverse("mentionable_list", args=[self.shared.pk]) + "?q=design",
            reverse("mentionable_new", args=[self.project.pk]) + "?q=design",
        ):
            entries = self.mentionable(self.cleo, url)
            self.assertEqual(entries, [])
            self.assertNotIn("Design", json.dumps(entries))

    def test_externals_see_the_members_they_may_know(self):
        """Pia knows the project's people (Bob through its all-access) but
        not Dora, who isn't counted"""
        [team] = self.teams(self.pia, reverse("mentionable", args=[self.todo.pk]))
        self.assertEqual(
            [member["id"] for member in team["members"]], [self.ada.pk, self.bob.pk]
        )
        self.assertEqual(
            team["detail"], "2 of 4: 1 can't see internal items, 1 inactive"
        )

    def test_not_in_the_api(self):
        self.client.force_login(self.ada)
        response = self.client.get(
            f"/api/v1/items/{self.todo.pk}/mentionable/?q=design"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


class PickerTest(Base):
    def test_assignees_on_the_list_page(self):
        self.client.force_login(self.ada)
        [team] = picker_teams(self.client.get(self.internal.get_absolute_url()))
        self.assertEqual(team["name"], "Design team")
        self.assertEqual(
            reasons(team),
            {
                self.ada.pk: "",
                # Offered, but assigning would make Bob a member: never
                self.bob.pk: "not a member of this project",
                self.cleo.pk: "can't see internal items",
                self.dora.pk: "not a member of this project",
                self.ian.pk: "inactive",
            },
        )

    def test_assignees_on_the_to_dos_page(self):
        self.client.force_login(self.ada)
        [team] = picker_teams(
            self.client.get(reverse("todo_edit", args=[self.todo.pk]))
        )
        self.assertEqual(reasons(team)[self.ada.pk], "")
        self.assertEqual(reasons(team)[self.cleo.pk], "can't see internal items")

    def test_subscribers(self):
        """Those subscribed already and oneself are in already"""
        subscribe(self.bob, self.todo)
        self.client.force_login(self.ada)
        [team] = picker_teams(
            self.client.get(reverse("item_subscribers", args=[self.todo.pk]))
        )
        already = {m["id"] for m in team["members"] if m["already"]}
        self.assertEqual(already, {self.ada.pk, self.bob.pk})
        # Subscribing doesn't add Bob to the project: offered to staff
        self.assertEqual(reasons(team)[self.cleo.pk], "can't see internal items")
        self.assertEqual(reasons(team)[self.ian.pk], "inactive")

    def test_also_tell_when_posting(self):
        self.client.force_login(self.ada)
        [team] = picker_teams(
            self.client.get(reverse("message_new", args=[self.project.pk]))
        )
        # Cleo is offered: the script leaves her out while the message is
        # internal
        self.assertEqual(reasons(team)[self.cleo.pk], "")
        self.assertEqual(reasons(team)[self.bob.pk], "not a member of this project")
        self.assertTrue(
            next(m for m in team["members"] if m["id"] == self.ada.pk)["already"]
        )

    def test_assigning_several(self):
        todo = ops.create_todo(todolist=self.shared, title="Review", creator=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(
            reverse("todos_assign") + f"?items={self.todo.pk}&items={todo.pk}"
        )
        [team] = picker_teams(response)
        self.assertEqual(reasons(team)[self.cleo.pk], "can't see internal items")

    def test_no_teams_for_clients(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "data-people-picker")
        self.assertIsNone(picker_teams(response))
        self.assertNotContains(response, "Design team")

    def test_no_empty_teams(self):
        team_ops.create_team(name="Nobody", actor=self.ada)
        self.client.force_login(self.ada)
        teams = picker_teams(self.client.get(self.internal.get_absolute_url()))
        self.assertEqual([team["name"] for team in teams], ["Design team"])


class ProjectGroupsTest(Base):
    """The whole project at once (specs/subscribers.md, decided 2026-11-23):
    the project's staff, and everybody while clients see it; staff only,
    in the subscribers modal and "Also tell…" """

    def test_subscribers_of_an_internal_item(self):
        """Staff only: Cleo can't see it; Ian is inactive"""
        self.client.force_login(self.ada)
        [staff] = picker_groups(
            self.client.get(reverse("item_subscribers", args=[self.todo.pk]))
        )
        self.assertEqual(staff["name"], "Staff on this project")
        self.assertEqual(ids(staff), [self.ada.pk, self.pia.pk])
        self.assertEqual(
            {m["id"] for m in staff["members"] if m["already"]}, {self.ada.pk}
        )
        self.assertEqual(reasons(staff)[self.pia.pk], "")

    def test_subscribers_of_a_visible_item(self):
        todo = ops.create_todo(todolist=self.shared, title="Review", creator=self.ada)
        self.client.force_login(self.ada)
        staff, everybody = picker_groups(
            self.client.get(reverse("item_subscribers", args=[todo.pk]))
        )
        self.assertEqual(ids(staff), [self.ada.pk, self.pia.pk])
        self.assertEqual(everybody["name"], "Everybody on this project")
        self.assertEqual(ids(everybody), [self.ada.pk, self.cleo.pk, self.pia.pk])
        self.assertEqual(reasons(everybody)[self.cleo.pk], "")

    def test_also_tell_when_posting(self):
        """At the top the clients follow "Visible to clients" in the
        browser: both are offered"""
        self.client.force_login(self.ada)
        groups = picker_groups(
            self.client.get(reverse("message_new", args=[self.project.pk]))
        )
        self.assertEqual([group["id"] for group in groups], ["staff", "everybody"])

    def test_picking_posts_people(self):
        """What's saved are the people picked, as one by one"""
        self.client.force_login(self.ada)
        self.client.post(
            reverse("item_subscribers", args=[self.todo.pk]),
            {"people": [self.pia.pk]},
        )
        self.assertTrue(
            Subscription.objects.filter(item=self.todo, user=self.pia).exists()
        )

    def test_not_when_assigning(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.internal.get_absolute_url())
        self.assertIsNotNone(picker_teams(response))
        self.assertIsNone(picker_groups(response))

    def test_not_for_clients(self):
        todo = ops.create_todo(todolist=self.shared, title="Review", creator=self.ada)
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("item_subscribers", args=[todo.pk]))
        self.assertContains(response, "data-people-picker")
        self.assertIsNone(picker_groups(response))

    def test_externals(self):
        self.client.force_login(self.pia)
        [staff] = picker_groups(
            self.client.get(reverse("item_subscribers", args=[self.todo.pk]))
        )
        self.assertEqual(ids(staff), [self.ada.pk, self.pia.pk])


class OnlyPeopleTest(Base):
    def test_changing_or_deleting_the_team_changes_nothing(self):
        """What the picker posts are people: the team isn't stored"""
        self.client.force_login(self.ada)
        self.client.post(
            reverse("item_subscribers", args=[self.todo.pk]),
            {"people": [self.bob.pk]},
        )
        ops.assign(self.todo, [self.ada], actor=self.ada)
        team_ops.update_team(self.team, members=[self.dora], actor=self.ada)
        team_ops.delete_team(self.team, actor=self.ada)
        self.assertEqual(list(self.todo.todo.assignees.all()), [self.ada])
        self.assertTrue(
            Subscription.objects.filter(item=self.todo, user=self.bob).exists()
        )
