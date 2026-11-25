from django.contrib import admin
from django.test import TestCase
from django.urls import reverse

from biwak.items.models import MessageCategory
from biwak.test_utils import person, project


class AdminTest(TestCase):
    """The admin is read only unless a model admin opts in (biwak/admin.py)"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.client.force_login(self.root)

    def test_pages_work(self):
        project(members=[self.root])
        MessageCategory.objects.create(name="Announcement", position=1)
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            with self.subTest(model=opts.label):
                url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)
                if model_admin.search_fields:
                    self.assertEqual(self.client.get(url, {"q": "a"}).status_code, 200)
                if (obj := model._default_manager.first()) is not None:
                    change = reverse(
                        f"admin:{opts.app_label}_{opts.model_name}_change",
                        args=[obj.pk],
                    )
                    self.assertEqual(self.client.get(change).status_code, 200)

    def test_read_only_unless_opted_in(self):
        """People and organizations are added and changed in the admin
        (never deleted: deactivated, merged), message categories edited;
        the rest changes through the app, Django's and allauth's admins
        included"""
        request = self.client.request().wsgi_request
        request.user = self.root
        rights = {
            model._meta.label: {
                right
                for right in ["add", "change", "delete"]
                if getattr(model_admin, f"has_{right}_permission")(request)
            }
            | {
                f"inline:{inline.model._meta.label}"
                for inline in model_admin.get_inline_instances(request)
                if inline.has_change_permission(request)
            }
            for model, model_admin in admin.site._registry.items()
        }
        self.assertEqual(
            {label: r for label, r in rights.items() if r},
            {
                "accounts.User": {"add", "change"},
                "organizations.Organization": {"add", "change"},
                "items.MessageCategory": {"add", "change", "delete"},
            },
        )

        website = project()
        response = self.client.post(
            reverse("admin:projects_project_change", args=[website.pk]),
            {"name": "Shop"},
        )
        self.assertEqual(response.status_code, 403)
        website.refresh_from_db()
        self.assertEqual(website.name, "Website")
