"""Inviting several people at once, and invitations visible
(specs/activation.md, "Inviting"): the operation, both entry points of the form,
the marks, resending, the filter, withdrawing, the API"""

import datetime as dt
import json

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from biwak.accounts.models import APIToken, User
from biwak.activity.models import Action, Event, LevelOverride
from biwak.items import operations as ops
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership
from biwak.test_utils import external, organization, person, project


def row(email, **kwargs):
    return {"email": email, **kwargs}


class OperationTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.website = project("Website", members=[self.ada])
        self.shop = project("Shop", members=[self.ada])

    def invite(self, people, *, actor=None, projects=None, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return project_ops.invite_people(
                projects or [self.website, self.shop],
                people,
                actor=actor or self.ada,
                **kwargs,
            )

    def test_several_people_and_projects(self):
        bob = person("Bob")
        organization("Example Client Ltd", domains=["client.example"])
        invited = self.invite(
            [
                row("dora@client.example", full_name="Dora Example"),
                row("bob@example.org"),
                row("eve@example.net", full_name="Eve Example"),
            ],
            notify="tagged",
        )
        self.assertEqual([i.created for i in invited], [True, False, True])
        dora = User.objects.get(email="dora@client.example")
        # The domain's organization, a client, who invited and when
        self.assertEqual(dora.organization.name, "Example Client Ltd")
        self.assertTrue(dora.is_client)
        self.assertEqual(dora.invited_by, self.ada)
        self.assertIsNotNone(dora.invited_at)
        self.assertTrue(dora.is_invited)
        # Bob had an account: added, not invited
        self.assertIsNone(bob.invited_at)
        for user in [dora, bob]:
            self.assertTrue(self.website.is_member(user))
            self.assertTrue(self.shop.is_member(user))
            # The choice for every project
            self.assertEqual(project_ops.notify_choice(user, self.shop), "tagged")
        self.assertEqual(
            Event.objects.filter(action=Action.ADDED, project=self.shop).count(), 3
        )
        # One mail per new person, naming both projects
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["dora@client.example", "eve@example.net"],
        )
        body = mail.outbox[0].body
        self.assertIn("Website", body)
        self.assertIn("Shop", body)
        self.assertIn(self.shop.get_absolute_url(), body)
        self.assertEqual(mail.outbox[0].subject, "Ada Example invited you to Biwak")

    def test_one_project_names_it(self):
        self.invite([row("dora@example.net")], projects=[self.website])
        self.assertEqual(mail.outbox[0].subject, "Ada Example invited you to Website")
        self.assertIn(self.website.get_absolute_url(), mail.outbox[0].body)

    def test_mails_after_the_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            project_ops.invite_people(
                [self.website], [row("dora@example.net")], actor=self.ada
            )
        self.assertEqual(len(mail.outbox), 0)
        for callback in callbacks:
            callback()
        self.assertEqual(len(mail.outbox), 1)

    def test_all_or_nothing_with_each_rows_error(self):
        gone = person("Gone", client=True, is_active=False, left_at=dt.date(2026, 3, 1))
        with self.assertRaises(project_ops.InvitationErrors) as cm:
            self.invite([
                row("dora@example.net"),
                row(gone.email),
                row("staff@example.net", is_client=False),
                row("own@example.net", organization=organization("Ours", is_own=True)),
                row("Dora@example.net"),
            ])
        self.assertEqual(
            cm.exception.errors,
            {
                1: "This person has been deactivated: activate them first.",
                2: "Only admins can invite staff.",
                3: "Only admins add people to your own organization or an external"
                " organization.",
                4: "This address is in another row too.",
            },
        )
        self.assertFalse(User.objects.filter(email="dora@example.net").exists())
        self.assertFalse(Event.objects.filter(action=Action.ADDED).exists())
        self.assertEqual(mail.outbox, [])

    def test_people_waiting_to_be_activated(self):
        """Decided 2026-11-28: inviting somebody an import created inactive
        activates them and sends the invitation, naming the projects
        they're in; waiting staff only by admins, like activating"""
        dora = person("Dora", client=True, is_active=False)
        archive = project("Archive", members=[])
        Membership.objects.create(project=archive, user=dora)
        [invited] = self.invite([row(dora.email)], projects=[self.website])
        dora.refresh_from_db()
        self.assertTrue(dora.is_active)
        self.assertFalse(invited.created)
        self.assertEqual(invited.added_to, [self.website])
        self.assertEqual(dora.invited_by, self.ada)
        self.assertTrue(dora.is_invited)
        [message] = mail.outbox
        self.assertEqual(message.to, [dora.email])
        self.assertIn("Website", message.body)
        self.assertIn("Archive", message.body)
        finn = person("Finn", is_active=False)
        with self.assertRaises(project_ops.InvitationErrors) as cm:
            self.invite([row(finn.email)])
        self.assertEqual(cm.exception.errors, {0: "Only admins can invite staff."})
        self.invite([row(finn.email)], actor=self.root)
        finn.refresh_from_db()
        self.assertTrue(finn.is_active)

    def test_admins_invite_staff(self):
        [invited] = self.invite(
            [row("staff@example.net", is_client=False)], actor=self.root
        )
        self.assertFalse(invited.user.is_client)

    def test_clients_and_externals_dont_invite(self):
        cleo = person("Cleo", client=True)
        pia = external()
        for actor in [cleo, pia]:
            with self.assertRaises(PermissionError):
                self.invite([row("dora@example.net")], actor=actor)

    def test_the_single_invite_calls_the_same_operation(self):
        user, changed = project_ops.invite(
            self.website, email="dora@example.net", actor=self.ada
        )
        self.assertTrue(changed)
        self.assertEqual(user.invited_by, self.ada)
        with self.assertRaisesMessage(
            project_ops.InvitationError, "Only admins can invite staff."
        ):
            project_ops.invite(
                self.website, email="eve@example.net", is_client=False, actor=self.ada
            )


class FormTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.cleo])
        self.shop = project("Shop", members=[self.ada])
        self.hidden = project("Hidden", all_access=False)
        self.url = reverse("invite_people")
        self.project_url = reverse("member_invite", args=[self.website.pk])

    def data(self, *rows, projects=None, notify="default"):
        data = {
            "projects": projects or [self.website.pk],
            "notify": notify,
            "person-TOTAL_FORMS": str(len(rows)),
            "person-INITIAL_FORMS": "0",
            "person-MIN_NUM_FORMS": "1",
            "person-MAX_NUM_FORMS": "50",
        }
        for index, values in enumerate(rows):
            for key, value in values.items():
                data[f"person-{index}-{key}"] = value
        return data

    def post(self, url, data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, data)

    def test_from_the_people_page(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("people"))
        self.assertContains(response, f'href="{self.url}"')
        response = self.client.get(self.url)
        self.assertContains(response, "Invite people")
        # Three rows without JavaScript, "Add another" for the script
        self.assertContains(response, 'name="person-2-email"')
        self.assertContains(response, "data-invite-add")
        # Only staff choose staff or client
        self.assertNotContains(response, "is_client")
        # The projects Ada can open, not the limited one
        self.assertContains(response, "Shop")
        self.assertNotContains(response, "Hidden")
        response = self.post(
            self.url,
            self.data(
                {"email": "dora@example.net", "full_name": "Dora Example"},
                {"email": "eve@example.net", "organization": "Example Client Ltd"},
                {},
                projects=[self.website.pk, self.shop.pk],
            ),
        )
        self.assertRedirects(response, reverse("people") + "?invited=1")
        dora = User.objects.get(email="dora@example.net")
        eve = User.objects.get(email="eve@example.net")
        self.assertEqual(eve.organization.name, "Example Client Ltd")
        self.assertTrue(self.shop.is_member(dora))
        self.assertTrue(self.website.is_member(eve))
        self.assertEqual(len(mail.outbox), 2)
        # A project the inviter can't open isn't accepted
        response = self.post(
            self.url,
            self.data({"email": "fay@example.net"}, projects=[self.hidden.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="fay@example.net").exists())

    def test_the_everything_new_help_says_what_it_does(self):
        """The default, "Only when tagged", needs no explaining; the other
        choice does (specs/notifications.md, "Levels"), in the invite and
        the add form"""
        self.client.force_login(self.ada)
        for url in [self.url, reverse("member_add", args=[self.website.pk])]:
            response = self.client.get(url)
            self.assertContains(
                response,
                "Everything new: every new message, doc or file tells the"
                " person and subscribes them to its comments.",
            )
            self.assertNotContains(response, "held back")

    def test_palette(self):
        from biwak.palette.test_actions import palette_data

        self.client.force_login(self.ada)
        labels = {
            (a["label"], a["group"])
            for a in palette_data(self.client.get(reverse("people")))["actions"]
        }
        self.assertIn(("Invite people", "page"), labels)
        self.client.force_login(self.cleo)
        labels = {
            a["label"]
            for a in palette_data(self.client.get(reverse("people")))["actions"]
        }
        self.assertNotIn("Invite people", labels)

    def test_from_a_projects_people_page(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_people", args=[self.website.pk]))
        self.assertContains(response, f'href="{self.project_url}"')
        response = self.client.get(self.project_url)
        self.assertContains(
            response,
            f'<input type="checkbox" name="projects" value="{self.website.pk}"'
            f' class="form-check-input" id="id_projects_1" checked>',
            html=True,
        )
        response = self.post(
            self.project_url,
            self.data({"email": "dora@example.net"}, notify="tagged"),
        )
        self.assertRedirects(
            response, reverse("project_people", args=[self.website.pk])
        )
        dora = User.objects.get(email="dora@example.net")
        self.assertEqual(project_ops.notify_choice(dora, self.website), "tagged")

    def test_errors_per_row_and_nothing_saved(self):
        self.client.force_login(self.ada)
        response = self.post(
            self.url,
            self.data(
                {"email": "dora@example.net"},
                {"email": "staff@example.net", "is_client": ""},
                {"email": "own@example.net", "organization": "Our organization"},
                {"email": "dora@example.net"},
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nobody has been invited")
        # Staff can't choose: the field isn't there, they're clients
        self.assertContains(
            response,
            "Only admins add people to your own organization or an external"
            " organization.",
        )
        self.assertContains(response, "This address is in another row too.")
        self.assertFalse(User.objects.filter(email="dora@example.net").exists())
        self.assertEqual(mail.outbox, [])
        # An address is needed in the first row; a name without one errs
        response = self.post(self.url, self.data({}, {"full_name": "Nobody"}))
        self.assertContains(response, "This field is required.")

    def test_new_organizations_only_with_the_invitations(self):
        self.client.force_login(self.ada)
        data = self.data(
            {
                "email": "dora@example.net",
                "organization": "Brand New Ltd",
                "create_organization": "on",
            },
            {"email": "staff@example.net", "organization": "Our organization"},
        )
        self.post(self.url, data)
        self.assertFalse(User.objects.filter(email="dora@example.net").exists())
        from biwak.organizations.models import Organization

        self.assertFalse(Organization.objects.filter(name="Brand New Ltd").exists())

    def test_admins_choose_staff(self):
        self.client.force_login(self.root)
        self.assertContains(self.client.get(self.url), 'name="person-0-is_client"')
        self.post(
            self.url,
            self.data(
                {"email": "staff@example.net", "is_client": ""},
                projects=[self.shop.pk],
            ),
        )
        self.assertFalse(User.objects.get(email="staff@example.net").is_client)

    def test_clients_and_externals_cant(self):
        pia = external()
        Membership.objects.create(project=self.website, user=pia)
        for user in [self.cleo, pia]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.get(self.project_url).status_code, 403)
            self.assertEqual(
                self.client.post(
                    self.url, self.data({"email": "x@example.net"})
                ).status_code,
                403,
            )
            self.assertNotContains(self.client.get(reverse("people")), self.url)
        self.assertFalse(User.objects.filter(email="x@example.net").exists())


class FilledInFromTheAddressTest(TestCase):
    """What a row fills in from its address (specs/activation.md, "Filled in
    from the address"): the organization the inviter may put people into,
    the role for admins only; nothing for those who can't open the form"""

    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        organization("Our organization", is_own=True, domains=["ours.example"])
        organization("Example Client Ltd", domains=["client.example"])
        self.pia = external(organization_name="Example External Agency")
        self.pia.organization.domains = ["agency.example"]
        self.pia.organization.save()
        self.url = reverse("invite_address")

    def lookup(self, email):
        response = self.client.get(self.url, {"email": email})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_admins_get_the_organization_and_the_role(self):
        self.client.force_login(self.root)
        client = organization("Example Client Ltd")
        self.assertEqual(
            self.lookup("dora@client.example"),
            {
                "organization": {"id": client.pk, "name": "Example Client Ltd"},
                "role": "client",
            },
        )
        self.assertEqual(
            self.lookup("bob@ours.example"),
            {
                "organization": {
                    "id": organization("Our organization").pk,
                    "name": "Our organization",
                },
                "role": "staff",
            },
        )
        self.assertEqual(
            self.lookup("Paul@Agency.example"),
            {
                "organization": {
                    "id": self.pia.organization_id,
                    "name": "Example External Agency",
                },
                "role": "staff",
            },
        )
        # Free mail and unknown domains: no organization, a client
        for email in ["eve@gmail.com", "eve@unknown.example"]:
            self.assertEqual(
                self.lookup(email), {"organization": None, "role": "client"}
            )
        # Not an address (yet): nothing
        for email in ["", "eve", "eve@"]:
            self.assertEqual(self.lookup(email), {"organization": None, "role": None})

    def test_staff_get_client_organizations_and_no_role(self):
        self.client.force_login(self.ada)
        self.assertEqual(
            self.lookup("dora@client.example"),
            {
                "organization": {
                    "id": organization("Example Client Ltd").pk,
                    "name": "Example Client Ltd",
                },
                "role": None,
            },
        )
        # Not the own or an external organization: they can't put people
        # there (org_ops.can_touch())
        for email in ["bob@ours.example", "paul@agency.example", "eve@gmail.com"]:
            self.assertEqual(self.lookup(email), {"organization": None, "role": None})

    def test_clients_and_externals_cant(self):
        cleo = person("Cleo", client=True)
        for user in [cleo, self.pia]:
            self.client.force_login(user)
            response = self.client.get(self.url, {"email": "dora@client.example"})
            self.assertEqual(response.status_code, 403)
            self.assertNotContains(response, "Example Client Ltd", status_code=403)
        self.client.logout()
        response = self.client.get(self.url, {"email": "dora@client.example"})
        self.assertNotEqual(response.status_code, 200)

    def test_the_form_takes_the_domains_organization_when_empty(self):
        self.client.force_login(self.ada)
        project_ = project("Website", members=[self.ada])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("invite_people"),
                {
                    "projects": [project_.pk],
                    "notify": "default",
                    "person-TOTAL_FORMS": "1",
                    "person-INITIAL_FORMS": "0",
                    "person-MIN_NUM_FORMS": "1",
                    "person-MAX_NUM_FORMS": "50",
                    "person-0-email": "dora@client.example",
                    "person-0-organization": "",
                },
            )
        self.assertEqual(
            User.objects.get(email="dora@client.example").organization.name,
            "Example Client Ltd",
        )


class InvitationsVisibleTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.cleo])
        self.shop = project("Shop", members=[self.ada])
        with self.captureOnCommitCallbacks(execute=True):
            [self.dora, self.eve] = [
                i.user
                for i in project_ops.invite_people(
                    [self.website],
                    [row("dora@example.net"), row("eve@example.net")],
                    actor=self.ada,
                )
            ]
        mail.outbox = []

    def test_marked_for_staff(self):
        self.client.force_login(self.bob)
        for url in [
            reverse("project_people", args=[self.website.pk]),
            reverse("people"),
            reverse("person", args=[self.dora.pk]),
        ]:
            response = self.client.get(url)
            self.assertContains(response, "Invited, not signed in yet")
            self.assertContains(response, "by Ada Example <time")
            self.assertContains(
                response, reverse("invitation_resend", args=[self.dora.pk])
            )
        # Not for clients
        self.client.force_login(self.cleo)
        for url in [
            reverse("project_people", args=[self.website.pk]),
            reverse("people"),
        ]:
            self.assertNotContains(self.client.get(url), "Invited, not signed in yet")
        # Signing in ends it
        self.dora.last_login = self.dora.invited_at
        self.dora.save()
        self.client.force_login(self.bob)
        response = self.client.get(reverse("person", args=[self.dora.pk]))
        self.assertNotContains(response, "Invited, not signed in yet")

    def test_the_invited_filter(self):
        # Oldest invitation first
        User.objects.filter(pk=self.eve.pk).update(
            invited_at=self.dora.invited_at.replace(year=2020)
        )
        self.client.force_login(self.bob)
        response = self.client.get(reverse("people") + "?invited=1")
        text = response.content.decode()
        self.assertLess(text.index("eve@example.net"), text.index("dora@example.net"))
        self.assertNotContains(response, "bob@example.org")
        # Clients get the people page as always
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("people") + "?invited=1")
        self.assertNotContains(response, "data-invitations")

    def test_resend(self):
        url = reverse("invitation_resend", args=[self.dora.pk])
        Membership.objects.create(project=self.shop, user=self.dora)
        self.client.force_login(self.bob)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"next": "/people/?invited=1"})
        self.assertRedirects(response, "/people/?invited=1")
        self.assertEqual(len(mail.outbox), 1)
        # The projects they're in now
        self.assertIn("Shop", mail.outbox[0].body)
        self.assertIn("Website", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].subject, "Bob Example invited you to Biwak")
        response = self.client.get(reverse("people"), follow=True)
        # No limit
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url)
        self.assertEqual(len(mail.outbox), 2)
        # Clients can't, and nobody once they signed in
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.dora.last_login = self.dora.invited_at
        self.dora.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(len(mail.outbox), 2)

    def test_withdraw_deletes_an_account_nothing_refers_to(self):
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.client.force_login(self.bob)
        response = self.client.get(url)
        self.assertContains(response, "Withdraw the invitation?")
        self.assertContains(response, "the account is deleted")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("people") + "?invited=1")
        self.assertFalse(User.objects.filter(pk=self.dora.pk).exists())
        # The feed's "added" events stay
        self.assertTrue(
            Event.objects.filter(action=Action.ADDED, data__user=self.dora.pk).exists()
        )

    def test_a_team_doesnt_keep_the_account(self):
        """Teams aren't among what keeps it (specs/activation.md; found
        2026-11-28, verification round 2)"""
        from biwak.teams import operations as team_ops

        team_ops.create_team(name="Client people", members=[self.dora], actor=self.ada)
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(url), "the account is deleted")
        self.client.post(url)
        self.assertFalse(User.objects.filter(pk=self.dora.pk).exists())

    def test_the_api_doesnt_invite_into_an_archived_project(self):
        """As the pages, which offer projects not archived (round 2)"""
        project_ops.archive_project(self.website, actor=self.ada)
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/v1/projects/{self.website.pk}/members/invite/",
                {"email": "eve@example.com"},
                content_type="application/json",
                headers={"Authorization": f"Bearer {secret}"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(User.objects.filter(email="eve@example.com").exists())

    def test_withdraw_keeps_an_account_something_refers_to(self):
        todolist = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        todo = ops.create_todo(todolist=todolist, title="Copy", creator=self.ada)
        ops.update_todo(todo, actor=self.ada, assignees=[self.dora])
        # Completed to-dos keep their assignees
        ops.complete(todo, actor=self.ada)
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(url), "the account is deactivated")
        response = self.client.post(url, {"next": "/people/"})
        self.assertRedirects(response, "/people/")
        self.dora.refresh_from_db()
        self.assertFalse(self.website.is_member(self.dora))

    def test_withdraw_unassigns_before_deciding(self):
        """Consistent (2026-11-28): open assignments go with withdrawing
        (``remove_member()``), so they don't keep the account, in the
        question either"""
        todolist = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        todo = ops.create_todo(todolist=todolist, title="Copy", creator=self.ada)
        ops.update_todo(todo, actor=self.ada, assignees=[self.dora])
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(url), "the account is deleted")
        self.client.post(url)
        self.assertFalse(User.objects.filter(pk=self.dora.pk).exists())
        self.assertEqual(list(todo.todo.assignees.all()), [])

    def test_withdraw_removes_from_projects_the_actor_cant_open(self):
        """Decided 2026-11-21: withdrawing is withdrawing, also from projects
        the withdrawing person can't open (counted, not named)"""
        secret = project("Secret", all_access=False, members=[self.dora])
        self.client.force_login(self.bob)
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        response = self.client.get(url)
        self.assertContains(
            response,
            "removed from Website, 1 project you can&#x27;t open and the account"
            " is deleted",
        )
        self.assertNotContains(response, "Secret")
        self.client.post(url)
        self.assertFalse(User.objects.filter(pk=self.dora.pk).exists())
        self.assertFalse(Membership.objects.filter(project=secret).exists())
        self.assertTrue(
            Event.objects.filter(
                action=Action.REMOVED, project=secret, data__user=self.dora.pk
            ).exists()
        )

    def test_withdraw_deactivates_in_projects_the_actor_cant_open(self):
        secret = project("Secret", all_access=False, members=[self.dora])
        todolist = ops.create_list(
            project=secret, title="Launch", creator=self.ada, visible=True
        )
        todo = ops.create_todo(todolist=todolist, title="Copy", creator=self.ada)
        ops.update_todo(todo, actor=self.ada, assignees=[self.dora])
        ops.complete(todo, actor=self.ada)
        self.client.force_login(self.bob)
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.assertContains(self.client.get(url), "the account is deactivated")
        self.client.post(url)
        self.dora.refresh_from_db()
        self.assertFalse(self.dora.is_active)
        self.assertFalse(secret.is_member(self.dora))
        self.assertFalse(self.website.is_member(self.dora))

    def test_withdraw_staff_only_and_before_signing_in(self):
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.post(
                reverse("invitation_withdraw", args=[self.bob.pk])
            ).status_code,
            404,
        )
        self.dora.last_login = self.dora.invited_at
        self.dora.save()
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(self.website.is_member(self.dora))

    def test_staff_manage_clients_invitations_admins_everybodys(self):
        """The split of activation.can_change() (specs/activation.md)"""
        root = person("Root", is_admin=True)
        with self.captureOnCommitCallbacks(execute=True):
            [fay] = [
                i.user
                for i in project_ops.invite_people(
                    [self.website],
                    [row("fay@example.org", is_client=False)],
                    actor=root,
                )
            ]
        resend = reverse("invitation_resend", args=[fay.pk])
        withdraw = reverse("invitation_withdraw", args=[fay.pk])
        self.client.force_login(self.bob)
        # Marked, without the buttons
        response = self.client.get(reverse("person", args=[fay.pk]))
        self.assertContains(response, "Invited, not signed in yet")
        self.assertNotContains(response, resend)
        self.assertNotContains(response, withdraw)
        self.assertContains(
            self.client.get(reverse("person", args=[self.dora.pk])),
            reverse("invitation_resend", args=[self.dora.pk]),
        )
        self.assertEqual(self.client.post(resend).status_code, 403)
        self.assertEqual(self.client.get(withdraw).status_code, 403)
        self.assertEqual(self.client.post(withdraw).status_code, 403)
        with self.assertRaises(PermissionError):
            project_ops.withdraw_invitation(fay, actor=self.bob)
        with self.assertRaises(PermissionError):
            project_ops.resend_invitation(fay, actor=self.bob)
        self.assertTrue(self.website.is_member(fay))
        # Admins may
        self.client.force_login(root)
        self.assertContains(self.client.get(reverse("person", args=[fay.pk])), withdraw)
        self.client.post(withdraw)
        self.assertFalse(User.objects.filter(pk=fay.pk).exists())

    def test_a_kept_account_is_deactivated(self):
        """Decided 2026-11-21: withdrawing an invitation whose account stays
        (something refers to it) deactivates it, ending its sessions, tokens
        and calendar links like deactivating does"""
        from biwak.accounts.models import CalendarToken

        todolist = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        todo = ops.create_todo(todolist=todolist, title="Copy", creator=self.ada)
        ops.update_todo(todo, actor=self.ada, assignees=[self.dora])
        ops.complete(todo, actor=self.ada)
        APIToken.create_for(user=self.dora, title="T", access="write")
        CalendarToken.objects.create(user=self.dora)
        url = reverse("invitation_withdraw", args=[self.dora.pk])
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(url), "deactivated")
        self.client.post(url)
        self.dora.refresh_from_db()
        self.assertFalse(self.dora.is_active)
        self.assertFalse(APIToken.objects.filter(user=self.dora).exists())
        self.assertFalse(CalendarToken.objects.filter(user=self.dora).exists())


class APITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.cleo])
        self.shop = project("Shop", members=[self.ada])

    def call(self, user, method, path, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        with self.captureOnCommitCallbacks(execute=True):
            return getattr(self.client, method)(
                f"/api/v1/{path}",
                json.dumps(data) if data is not None else None,
                content_type="application/json",
                headers={"authorization": f"Bearer {secret}"},
            )

    def test_inviting(self):
        bob = person("Bob")
        response = self.call(
            self.ada,
            "post",
            "invitations/",
            {
                "people": [
                    {"email": "dora@example.net", "name": "Dora Example"},
                    {"email": bob.email},
                ],
                "projects": [self.website.pk, self.shop.pk],
                "notify": "tagged",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual([d["created"] for d in data], [True, False])
        self.assertEqual(data[0]["person"]["name"], "Dora Example")
        self.assertEqual(data[1]["added_to"], [self.website.pk, self.shop.pk])
        self.assertEqual(len(mail.outbox), 1)
        dora = User.objects.get(email="dora@example.net")
        self.assertEqual(project_ops.notify_choice(dora, self.shop), "tagged")

    def test_errors_per_row(self):
        response = self.call(
            self.ada,
            "post",
            "invitations/",
            {
                "people": [
                    {"email": "dora@example.net"},
                    {"email": "staff@example.net", "is_client": False},
                    {"email": "nope"},
                    {"email": "eve@example.net", "organization": "Unknown Ltd"},
                ],
                "projects": [self.website.pk],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["errors"],
            [
                {"index": 2, "detail": "Enter a valid email address."},
                {"index": 3, "detail": "No such organization."},
            ],
        )
        response = self.call(
            self.ada,
            "post",
            "invitations/",
            {
                "people": [
                    {"email": "dora@example.net"},
                    {"email": "staff@example.net", "is_client": False},
                ],
                "projects": [self.website.pk],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["errors"],
            [{"index": 1, "detail": "Only admins can invite staff."}],
        )
        self.assertIn("staff@example.net: Only admins", response.json()["detail"])
        self.assertFalse(User.objects.filter(email="dora@example.net").exists())
        self.assertEqual(mail.outbox, [])

    def test_projects_one_can_open(self):
        hidden = project("Hidden", all_access=False)
        response = self.call(
            self.ada,
            "post",
            "invitations/",
            {"people": [{"email": "dora@example.net"}], "projects": [hidden.pk]},
        )
        self.assertEqual(response.status_code, 404)

    def test_clients_and_externals_cant(self):
        pia = external()
        Membership.objects.create(project=self.website, user=pia)
        dora, _created = project_ops.invite(
            self.website, email="dora@example.net", actor=self.ada
        )
        for user in [self.cleo, pia]:
            for method, path in [
                ("post", "invitations/"),
                ("get", "invitations/"),
                ("post", f"invitations/{dora.pk}/resend/"),
                ("delete", f"invitations/{dora.pk}/"),
            ]:
                data = (
                    {
                        "people": [{"email": "x@example.net"}],
                        "projects": [self.website.pk],
                    }
                    if path == "invitations/" and method == "post"
                    else None
                )
                response = self.call(user, method, path, data)
                self.assertEqual(response.status_code, 403, (user, method, path))
        self.assertTrue(User.objects.filter(pk=dora.pk).exists())

    def test_staff_only_for_clients_invitations(self):
        with self.captureOnCommitCallbacks(execute=True):
            fay, _created = project_ops.invite(
                self.website, email="fay@example.org", is_client=False, actor=self.root
            )
        self.assertEqual(
            self.call(self.ada, "post", f"invitations/{fay.pk}/resend/").status_code,
            403,
        )
        self.assertEqual(
            self.call(self.ada, "delete", f"invitations/{fay.pk}/").status_code, 403
        )
        self.assertTrue(User.objects.filter(pk=fay.pk).exists())
        # A kept account is deactivated
        ops.create_list(project=self.website, title="Launch", creator=fay, visible=True)
        response = self.call(self.root, "delete", f"invitations/{fay.pk}/")
        self.assertEqual(
            response.json(),
            {
                "removed_from": [self.website.pk],
                "removed_from_others": 0,
                "deleted": False,
                "deactivated": True,
            },
        )
        fay.refresh_from_db()
        self.assertFalse(fay.is_active)

    def test_list_resend_withdraw(self):
        with self.captureOnCommitCallbacks(execute=True):
            dora, _created = project_ops.invite(
                self.website, email="dora@example.net", actor=self.ada
            )
        mail.outbox = []
        data = self.call(self.root, "get", "invitations/").json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["email"], "dora@example.net")
        self.assertEqual(data[0]["invited_by"]["name"], "Ada Example")
        self.assertEqual(data[0]["project_ids"], [self.website.pk])
        response = self.call(self.root, "post", f"invitations/{dora.pk}/resend/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        response = self.call(self.root, "delete", f"invitations/{dora.pk}/")
        self.assertEqual(
            response.json(),
            {
                "removed_from": [self.website.pk],
                "removed_from_others": 0,
                "deleted": True,
                "deactivated": False,
            },
        )
        self.assertFalse(User.objects.filter(pk=dora.pk).exists())
        self.assertEqual(
            self.call(self.root, "delete", f"invitations/{dora.pk}/").status_code, 404
        )
        # LevelOverride rows went with the account
        self.assertFalse(LevelOverride.objects.filter(user_id=dora.pk).exists())
