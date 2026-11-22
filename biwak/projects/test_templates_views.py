"""Templates (specs/templates.md): the pages, as own staff, a client and an
external"""

from django.test import TestCase
from django.urls import reverse

from biwak.activity.models import Action, Event
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.palette.test_actions import palette_data
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership, Project
from biwak.projects.test_templates import Fixture
from biwak.test_utils import MODAL, assert_modal, assert_modal_redirect, project


class Base(Fixture):
    def setUp(self):
        super().setUp()
        self.website = project("Website", members=[self.ada, self.cleo, self.pia])
        # A member, still nothing: templates are the own staff's
        Membership.objects.create(project=self.template, user=self.cleo)
        Membership.objects.create(project=self.template, user=self.pia)


class TemplatesPageTest(Base, TestCase):
    def test_staff(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("templates"))
        self.assertContains(response, "Web project")
        self.assertContains(
            response, "1 list · 2 to-dos · 2 messages · 2 folders · 1 doc · 1 file"
        )
        self.assertContains(
            response, f"{reverse('project_create')}?template={self.template.pk}"
        )

    def test_checkins(self):
        """Counted on the card; one visible to clients named in the new
        project form"""
        checkin_ops.create_question(
            project=self.template,
            title="Anything blocking?",
            creator=self.ada,
            visible=True,
            **MONDAY_9,
        )
        self.client.force_login(self.bob)
        response = self.client.get(reverse("templates"))
        self.assertContains(response, "1 list · 2 to-dos · 1 check-in · 2 messages")
        url = f"{reverse('project_create')}?template={self.template.pk}"
        response = self.client.get(url, headers=MODAL)
        self.assertContains(
            response, "Visible to clients: Anything blocking?, Onboarding and Welcome"
        )

    def test_others_get_404(self):
        for user in [self.cleo, self.pia]:
            with self.subTest(user=user):
                self.client.force_login(user)
                for url in [
                    reverse("templates"),
                    reverse("template_create"),
                    self.template.get_absolute_url(),
                    reverse("project_todos", args=[self.template.pk]),
                    self.list.get_absolute_url(),
                    self.welcome.get_absolute_url(),
                    f"{reverse('project_create')}?template={self.template.pk}",
                    reverse("list_from_template", args=[self.website.pk]),
                ]:
                    self.assertIn(self.client.get(url).status_code, {403, 404}, url)
                response = self.client.get(reverse("templates"))
                self.assertEqual(response.status_code, 404)

    def test_archived(self):
        project_ops.archive_project(self.template, actor=self.ada)
        self.client.force_login(self.ada)
        self.assertNotContains(self.client.get(reverse("templates")), "Web project")
        response = self.client.get(reverse("templates") + "?archived=1")
        self.assertContains(response, "Web project")
        # Not among the archived projects
        self.assertNotContains(
            self.client.get(reverse("projects") + "?archived=1"), "Web project"
        )

    def test_not_on_the_projects_page(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("projects"))
        self.assertNotContains(response, "Web project")
        self.assertContains(response, reverse("templates"))
        self.client.force_login(self.cleo)
        self.assertNotContains(
            self.client.get(reverse("projects")), reverse("templates")
        )

    def test_new_template(self):
        self.client.force_login(self.bob)
        url = reverse("template_create")
        assert_modal(self, self.client.get(url, headers=MODAL), title="New template")
        response = self.client.post(
            url, {"name": "Event", "description": "", "color": ""}, headers=MODAL
        )
        template = Project.objects.get(name="Event")
        assert_modal_redirect(self, response, template.get_absolute_url())
        self.assertTrue(template.is_template)
        self.assertTrue(template.is_all_access)
        self.assertFalse(template.memberships.exists())


class TemplatePageTest(Base, TestCase):
    def test_project_page(self):
        self.client.force_login(self.bob)
        response = self.client.get(self.template.get_absolute_url())
        self.assertContains(response, "data-template-note")
        self.assertContains(response, "New project from this…")
        self.assertNotContains(
            response, reverse("project_join", args=[self.template.pk])
        )
        self.assertNotContains(response, ">Members")

    def test_no_joining_or_adding(self):
        self.client.force_login(self.bob)
        response = self.client.post(reverse("project_join", args=[self.template.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("member_add", args=[self.template.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("member_invite", args=[self.template.pk]))
        self.assertEqual(response.status_code, 404)

    def test_edit_keeps_all_access(self):
        self.client.force_login(self.ada)
        url = reverse("project_edit", args=[self.template.pk])
        response = self.client.get(url, headers=MODAL)
        assert_modal(self, response, title="Edit the template")
        self.assertNotContains(response, "is_all_access")

    def test_palette(self):
        self.client.force_login(self.ada)
        data = palette_data(self.client.get(self.template.get_absolute_url()))
        labels = [action["label"] for action in data["actions"]]
        self.assertIn("New project from this…", labels)
        self.assertIn("Go to templates", labels)
        data = palette_data(self.client.get(reverse("templates")))
        self.assertIn("New template", [a["label"] for a in data["actions"]])
        data = palette_data(self.client.get(self.website.get_absolute_url()))
        labels = [action["label"] for action in data["actions"]]
        self.assertIn("New list from a template…", labels)
        self.assertNotIn("New project from this…", labels)
        self.client.force_login(self.cleo)
        data = palette_data(self.client.get(self.website.get_absolute_url()))
        labels = [action["label"] for action in data["actions"]]
        self.assertNotIn("Go to templates", labels)
        self.assertNotIn("New list from a template…", labels)


class NewProjectTest(Base, TestCase):
    def test_from_this(self):
        """Prefilled from the template, saying what clients will see"""
        self.client.force_login(self.ada)
        url = f"{reverse('project_create')}?template={self.template.pk}"
        response = self.client.get(url, headers=MODAL)
        assert_modal(self, response, title="New project from Web project")
        self.assertContains(response, "For websites")
        self.assertContains(response, "Visible to clients: Onboarding and Welcome")
        response = self.client.post(
            url,
            {
                "template": self.template.pk,
                "name": "Shop",
                "description": "A shop",
                "is_all_access": "on",
                "color": "",
            },
            headers=MODAL,
        )
        shop = Project.objects.get(name="Shop")
        assert_modal_redirect(self, response, shop.get_absolute_url())
        self.assertTrue(
            Item.objects.filter(
                project=shop, kind=Kind.LIST, title="Onboarding"
            ).exists()
        )
        self.assertTrue(
            Event.objects.filter(
                project=shop, action=Action.CREATED, item=None
            ).exists()
        )
        response = self.client.get(shop.get_absolute_url())
        self.assertContains(response, "from the template Web project")

    def test_chosen_in_the_form(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_create"), headers=MODAL)
        self.assertContains(response, "From a template")
        self.client.post(
            reverse("project_create"),
            {
                "template": self.template.pk,
                "name": "Shop",
                "is_all_access": "on",
                "color": "",
            },
            headers=MODAL,
        )
        shop = Project.objects.get(name="Shop")
        self.assertEqual(Item.objects.filter(project=shop, parent=None).count(), 4)

    def test_with_organizations(self):
        """The template goes along to the second step"""
        self.client.force_login(self.ada)
        organization = self.cleo.organization
        response = self.client.post(
            reverse("project_create"),
            {
                "template": self.template.pk,
                "name": "Shop",
                "is_all_access": "on",
                "color": "",
                "organizations": [organization.pk],
            },
            headers=MODAL,
        )
        self.assertContains(response, "Visible to clients")
        self.assertContains(response, f'name="template" value="{self.template.pk}"')

    def test_unknown_template(self):
        self.client.force_login(self.ada)
        response = self.client.get(
            f"{reverse('project_create')}?template={self.website.pk}"
        )
        self.assertEqual(response.status_code, 404)

    def test_no_templates_no_field(self):
        Project.objects.filter(is_template=True).delete()
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_create"), headers=MODAL)
        self.assertNotContains(response, "From a template")


class ListFromTemplateTest(Base, TestCase):
    def test_two_steps(self):
        self.client.force_login(self.ada)
        url = reverse("list_from_template", args=[self.website.pk])
        response = self.client.get(reverse("list_new", args=[self.website.pk]))
        self.assertContains(response, url)
        response = self.client.get(url, headers=MODAL)
        assert_modal(self, response, title="New list from a template")
        self.assertContains(response, "Onboarding · Web project")
        response = self.client.post(url, {"source": self.list.pk}, headers=MODAL)
        self.assertContains(response, 'value="Onboarding"')
        self.assertContains(response, "From Onboarding · Web project.")
        response = self.client.post(
            url,
            {
                "step": "copy",
                "source": self.list.pk,
                "title": "Onboarding Dan",
                "dates": "remove",
            },
            headers=MODAL,
        )
        copy = Item.objects.get(project=self.website, title="Onboarding Dan")
        assert_modal_redirect(self, response, copy.get_absolute_url())
        self.assertEqual(
            [t.title for t in ops.open_todos(copy)], ["Kick-off", "Review"]
        )
        self.assertFalse(copy.is_client_visible)

    def test_visible_asks(self):
        """Visible to the project's clients: asked first, as when copying"""
        self.client.force_login(self.ada)
        url = reverse("list_from_template", args=[self.website.pk])
        data = {
            "step": "copy",
            "source": self.list.pk,
            "title": "Onboarding",
            "dates": "keep",
            "visible": "on",
        }
        response = self.client.post(url, data, headers=MODAL)
        self.assertContains(response, "data-new-clients")
        self.assertFalse(Item.objects.filter(project=self.website).exists())
        data["confirmed"] = f"{self.list.pk}:1"
        assert_modal_redirect(self, self.client.post(url, data, headers=MODAL))
        self.assertTrue(
            Item.objects.get(project=self.website, kind=Kind.LIST).is_client_visible
        )

    def test_only_template_lists(self):
        other = ops.create_list(project=self.website, title="Mine", creator=self.ada)
        self.client.force_login(self.ada)
        url = reverse("list_from_template", args=[self.website.pk])
        response = self.client.post(url, {"source": other.pk}, headers=MODAL)
        self.assertNotContains(response, 'value="Mine"')
