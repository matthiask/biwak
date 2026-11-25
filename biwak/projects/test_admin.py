from django.test import TestCase

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
        # The project and its memberships change through the app
        response = self.client.post(self.url, {"name": "Website"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            list(self.project.memberships.values_list("user", flat=True)),
            [self.ada.pk],
        )
