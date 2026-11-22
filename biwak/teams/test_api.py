"""``/api/v1/teams/`` and ``biwak teams`` (specs/teams.md): staff read,
own staff change, clients get 404"""

import json

from django.test import TestCase

from biwak import test_cli
from biwak.accounts.models import APIToken
from biwak.teams import operations as team_ops
from biwak.teams.models import Team
from biwak.test_utils import partner, person, project


class APITest(TestCase):
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

    def api(self, user, method, path, data=None):
        self.client.force_login(user)
        return getattr(self.client, method)(
            f"/api/v1/{path}", data, content_type="application/json"
        )

    def test_staff_read_teams_with_their_members(self):
        response = self.api(self.ada, "get", "teams/")
        self.assertEqual(response.status_code, 200)
        [team] = response.json()
        self.assertEqual(team["name"], "Design team")
        self.assertEqual(
            [p["id"] for p in team["members"]],
            [self.bob.pk, self.cleo.pk, self.dora.pk],
        )
        self.assertTrue(team["url"].endswith(self.team.get_absolute_url()))
        detail = self.api(self.ada, "get", f"teams/{self.team.pk}/").json()
        self.assertEqual(detail, team)

    def test_partners_read_the_members_they_may_know(self):
        # Bob through the all-access project, not Dora
        [team] = self.api(self.pia, "get", "teams/").json()
        self.assertEqual(
            [p["id"] for p in team["members"]], [self.bob.pk, self.cleo.pk]
        )
        response = self.api(self.pia, "post", "teams/", {"name": "Mine"})
        self.assertEqual(response.status_code, 403)
        for method in ("patch", "delete"):
            response = self.api(
                self.pia, method, f"teams/{self.team.pk}/", {"name": "Mine"}
            )
            self.assertEqual(response.status_code, 403)
        self.assertEqual(Team.objects.get().name, "Design team")

    def test_clients_get_404(self):
        for method, path in [
            ("get", "teams/"),
            ("post", "teams/"),
            ("get", f"teams/{self.team.pk}/"),
            ("patch", f"teams/{self.team.pk}/"),
            ("delete", f"teams/{self.team.pk}/"),
        ]:
            response = self.api(self.cleo, method, path, {"name": "Mine"})
            self.assertEqual(response.status_code, 404, (method, path))
            self.assertNotIn("Design", response.content.decode())
        self.assertTrue(Team.objects.exists())

    def test_create_change_delete(self):
        response = self.api(
            self.bob, "post", "teams/", {"name": "Writers", "members": [self.ada.pk]}
        )
        self.assertEqual(response.status_code, 201)
        team = response.json()
        self.assertEqual([p["id"] for p in team["members"]], [self.ada.pk])
        # A taken name and unknown people are refused
        response = self.api(self.bob, "post", "teams/", {"name": "writers"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("There is a team called", response.json()["detail"])
        response = self.api(
            self.bob, "patch", f"teams/{team['id']}/", {"members": [999999]}
        )
        self.assertEqual(response.status_code, 400)
        response = self.api(
            self.bob,
            "patch",
            f"teams/{team['id']}/",
            {"name": "Editors", "members": [self.cleo.pk, self.bob.pk]},
        )
        self.assertEqual(response.json()["name"], "Editors")
        self.assertEqual(
            [p["id"] for p in response.json()["members"]], [self.bob.pk, self.cleo.pk]
        )
        response = self.api(self.bob, "delete", f"teams/{team['id']}/")
        self.assertEqual(response.json()["name"], "Editors")
        self.assertFalse(Team.objects.filter(pk=team["id"]).exists())
        self.assertEqual(
            self.api(self.bob, "get", f"teams/{team['id']}/").status_code, 404
        )


class CLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)

    def test_teams(self):
        output = self.biwak(
            "teams", "add", "Design team", "--members", f"{self.bob.pk},{self.cleo.pk}"
        ).output
        self.assertIn("Created: Design team", output)
        self.assertIn(f"Cleo Example ({self.cleo.pk}, client)", output)
        team = Team.objects.get()
        output = self.biwak("teams").output
        self.assertIn("Design team", output)
        self.assertIn(f"Bob Example ({self.bob.pk})", output)
        data = json.loads(self.biwak("teams", "show", team.pk, "--json").stdout)
        self.assertEqual(
            [p["id"] for p in data["members"]], [self.bob.pk, self.cleo.pk]
        )
        output = self.biwak(
            "teams", "edit", team.pk, "--name", "Designers", "--members", self.ada.pk
        ).output
        self.assertIn("Designers", output)
        self.assertEqual(list(team.members.all()), [self.ada])
        # --members alone leaves the name, an empty one removes everybody
        self.biwak("teams", "edit", team.pk, "--members", "")
        self.assertFalse(team.members.exists())
        self.assertIn(
            "Deleted Designers", self.biwak("teams", "delete", team.pk).output
        )
        self.assertFalse(Team.objects.exists())

    def test_clients_get_404(self):
        team_ops.create_team(name="Design team", actor=self.ada)
        _token, token = APIToken.create_for(user=self.cleo, title="T", access="write")
        test_cli.biwak_cli.core.write_config({
            "url": "http://testserver",
            "token": token,
        })
        with test_cli.patch.object(
            test_cli.biwak_cli.commands.console, "_color_system", None
        ):
            result = test_cli.CliRunner().invoke(test_cli.biwak_cli.cli, ["teams"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)
        self.assertNotIn("Design", result.output)
