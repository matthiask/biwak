"""Task lists in the API (specs/editor.md): disabled checkboxes in
``*_html``, the counts next to them"""

from django.core.files.base import ContentFile
from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.test_utils import person, project


TEXT = "- [x] tent\n- [ ] stove\n- [ ] rope"


class ChecklistAPITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        self.items = {
            "todos": ops.create_todo(
                todolist=todolist, title="Pack", creator=self.ada, notes=TEXT
            ),
            "messages": ops.create_message(
                project=self.project,
                title="News",
                creator=self.ada,
                content=TEXT,
                visible=True,
            ),
            "docs": ops.create_doc(
                project=self.project,
                title="Plan",
                creator=self.ada,
                content=TEXT,
                visible=True,
            ),
            "files": ops.create_upload(
                project=self.project,
                file=ContentFile(b"x", name="a.txt"),
                creator=self.ada,
                description=TEXT,
                visible=True,
            ),
        }

    def get(self, user, path):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return self.client.get(
            f"/api/v1/{path}", headers={"authorization": f"Bearer {secret}"}
        )

    def test_counts_and_html(self):
        for user in [self.ada, self.cleo]:
            for kind, item in self.items.items():
                response = self.get(user, f"{kind}/{item.pk}/")
                self.assertEqual(response.status_code, 200, (user, kind))
                data = response.json()
                self.assertEqual(
                    (data["checklist_done"], data["checklist_total"]), (1, 3), kind
                )
                html = next(v for k, v in data.items() if k.endswith("_html"))
                self.assertIn('type="checkbox"', html)
                self.assertEqual(html.count("disabled"), 3)

    def test_no_checklist(self):
        ops.update_todo(self.items["todos"], actor=self.ada, notes="Plain")
        data = self.get(self.ada, f"todos/{self.items['todos'].pk}/").json()
        self.assertEqual((data["checklist_done"], data["checklist_total"]), (0, 0))
