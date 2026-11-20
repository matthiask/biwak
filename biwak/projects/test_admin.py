from django.test import TestCase

from biwak.projects.models import Membership
from biwak.test_utils import person, project


class ProjectAdminTest(TestCase):
    """Admins join through the app, which records the event: the
    memberships are read-only in the Django admin"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        self.client.force_login(self.root)
        self.url = f"/admin/projects/project/{self.project.pk}/change/"

    def test_memberships_are_read_only(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Ada Example")
        self.assertNotContains(response, 'name="memberships-0-user"')
        # Saving the project with a membership added and one deleted
        now = {"0": "2026-11-20", "1": "12:00:00"}
        data = {"name": "Website", "is_all_access": "on"}
        data |= {f"created_at_{k}": v for k, v in now.items()}
        data |= {
            "memberships-TOTAL_FORMS": "2",
            "memberships-INITIAL_FORMS": "1",
            "memberships-MIN_NUM_FORMS": "0",
            "memberships-MAX_NUM_FORMS": "1000",
            "memberships-0-id": Membership.objects.get().pk,
            "memberships-0-project": self.project.pk,
            "memberships-0-user": self.ada.pk,
            "memberships-0-DELETE": "on",
            **{f"memberships-0-created_at_{k}": v for k, v in now.items()},
            **{f"memberships-1-created_at_{k}": v for k, v in now.items()},
            "memberships-1-project": self.project.pk,
            "memberships-1-user": self.root.pk,
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(self.project.memberships.values_list("user", flat=True)),
            [self.ada.pk],
        )
