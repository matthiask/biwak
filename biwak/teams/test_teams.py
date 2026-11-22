"""Managing teams (specs/teams.md): the operations, the People page's
section, a team's page and its modals, the palette; own staff manage,
partners see, clients never do"""

import json
import re

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from biwak.audit.models import LoggedAction
from biwak.teams import operations as team_ops
from biwak.teams.models import Team, TeamMember
from biwak.test_utils import partner, person, project


class OperationsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.pia = partner("Pia")

    def test_create_update_delete(self):
        LoggedAction.objects.all().delete()
        team = team_ops.create_team(
            name="  Design   team ", members=[self.ada, self.cleo.pk], actor=self.ada
        )
        self.assertEqual(team.name, "Design team")
        self.assertEqual(set(team.members.all()), {self.ada, self.cleo})
        team_ops.update_team(
            team, name="Designers", members=[self.cleo, self.pia], actor=self.bob
        )
        team.refresh_from_db()
        self.assertEqual(team.name, "Designers")
        self.assertEqual(set(team.members.all()), {self.cleo, self.pia})
        # None leaves either alone
        team_ops.update_team(team, actor=self.bob)
        self.assertEqual(set(team.members.all()), {self.cleo, self.pia})
        team_ops.delete_team(team, actor=self.bob)
        self.assertFalse(Team.objects.exists())
        self.assertFalse(TeamMember.objects.exists())
        # In the audit log, both tables
        logged = {(a.table_name, a.action) for a in LoggedAction.objects.all()}
        self.assertLessEqual(
            {
                ("teams_team", "I"),
                ("teams_team", "U"),
                ("teams_team", "D"),
                ("teams_teammember", "I"),
                ("teams_teammember", "D"),
            },
            logged,
        )

    def test_names_are_unique_ignoring_case(self):
        team_ops.create_team(name="Design", actor=self.ada)
        with self.assertRaises(ValidationError):
            team_ops.create_team(name="design ", actor=self.ada)
        with self.assertRaises(ValidationError):
            team_ops.create_team(name="  ", actor=self.ada)
        other = team_ops.create_team(name="Other", actor=self.ada)
        with self.assertRaises(ValidationError):
            team_ops.update_team(other, name="DESIGN", actor=self.ada)
        # Keeping its own name is fine
        team_ops.update_team(other, name="other", actor=self.ada)

    def test_unknown_people_are_refused(self):
        with self.assertRaises(ValidationError):
            team_ops.create_team(name="Design", members=[999999], actor=self.ada)
        self.assertFalse(Team.objects.exists())

    def test_only_own_staff_manage(self):
        team = team_ops.create_team(name="Design", actor=self.ada)
        for actor in (self.pia, self.cleo):
            with self.assertRaises(PermissionError):
                team_ops.create_team(name="Other", actor=actor)
            with self.assertRaises(PermissionError):
                team_ops.update_team(team, name="Other", actor=actor)
            with self.assertRaises(PermissionError):
                team_ops.delete_team(team, actor=actor)

    def test_deleting_a_person_removes_them(self):
        team = team_ops.create_team(
            name="Design", members=[self.ada, self.bob], actor=self.ada
        )
        self.bob.is_active = False
        self.bob.save()
        # Deactivating keeps them
        self.assertEqual(set(team.members.all()), {self.ada, self.bob})
        self.bob.delete()
        self.assertEqual(set(team.members.all()), {self.ada})


def palette_data(response):
    match = re.search(
        r'<script id="wb-palette-data" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.DOTALL,
    )
    return json.loads(match[1])


def page_labels(response):
    return [
        a["label"] for a in palette_data(response)["actions"] if a["group"] == "page"
    ]


class PagesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.dora = person("Dora", client=True, organization="Other Client Ltd")
        self.pia = partner("Pia")
        project(members=[self.pia, self.cleo])
        self.team = team_ops.create_team(
            name="Design team", members=[self.bob, self.cleo, self.dora], actor=self.ada
        )

    def test_people_page_as_own_staff(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("people"))
        self.assertContains(response, 'id="teams"')
        self.assertContains(response, "Design team")
        self.assertContains(response, reverse("team_create"))
        self.assertIn("New team", page_labels(response))
        # Not under the filters
        response = self.client.get(reverse("people") + "?inactive=1")
        self.assertNotContains(response, "Design team")

    def test_people_page_as_partner(self):
        """Partners see the teams with the members they may know, and can't
        manage them"""
        self.client.force_login(self.pia)
        response = self.client.get(reverse("people"))
        self.assertContains(response, "Design team")
        self.assertNotContains(response, reverse("team_create"))
        self.assertNotIn("New team", page_labels(response))
        section = response.content.decode().split('id="teams"')[1]
        self.assertIn("Cleo", section)
        self.assertNotIn("Dora", section)
        response = self.client.get(self.team.get_absolute_url())
        self.assertContains(response, "Cleo Example")
        self.assertNotContains(response, "Dora")
        self.assertNotContains(response, reverse("team_edit", args=[self.team.pk]))
        for url in (
            reverse("team_create"),
            reverse("team_edit", args=[self.team.pk]),
            reverse("team_delete", args=[self.team.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("team_delete", args=[self.team.pk])).status_code,
            403,
        )
        self.assertTrue(Team.objects.exists())

    def test_clients_never_see_teams(self):
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("people"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Design team")
        self.assertNotContains(response, 'id="teams"')
        for url in (
            self.team.get_absolute_url(),
            reverse("team_create"),
            reverse("team_edit", args=[self.team.pk]),
            reverse("team_delete", args=[self.team.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(
            self.client.post(reverse("team_delete", args=[self.team.pk])).status_code,
            404,
        )

    def test_team_page_and_palette(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.team.get_absolute_url())
        self.assertContains(response, "Design team")
        self.assertContains(response, "Dora Example")
        self.assertContains(response, reverse("team_edit", args=[self.team.pk]))
        self.assertEqual(page_labels(response), ["Edit", "Delete"])

    def test_create_in_a_modal(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("team_create"), headers={"HX-Modal": "1"})
        self.assertContains(response, "data-people-picker")
        # No teams in the team's own picker
        self.assertNotContains(response, "data-teams")
        response = self.client.post(
            reverse("team_create"),
            {"name": "Writers", "members": [self.ada.pk, self.dora.pk]},
        )
        team = Team.objects.get(name="Writers")
        self.assertRedirects(response, team.get_absolute_url())
        self.assertEqual(set(team.members.all()), {self.ada, self.dora})
        # A taken name is the form's error
        response = self.client.post(
            reverse("team_create"), {"name": "design TEAM", "members": []}
        )
        self.assertContains(response, "There is a team called")

    def test_edit_and_delete(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("team_edit", args=[self.team.pk]),
            {"name": "Designers", "members": [self.ada.pk]},
        )
        self.assertRedirects(response, self.team.get_absolute_url())
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Designers")
        self.assertEqual(list(self.team.members.all()), [self.ada])
        response = self.client.get(reverse("team_delete", args=[self.team.pk]))
        self.assertContains(response, "Delete Designers?")
        response = self.client.post(reverse("team_delete", args=[self.team.pk]))
        self.assertRedirects(response, reverse("people") + "#teams")
        self.assertFalse(Team.objects.exists())
