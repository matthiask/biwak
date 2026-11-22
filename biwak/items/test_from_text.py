"""Adding to-dos from text (specs/todos-from-text.md): the parser, the
operation, the modal and its preview, the API"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from biwak.activity import mails
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.activity.operations import subscribe
from biwak.items import from_text, operations as ops
from biwak.items.models import Item, Kind
from biwak.palette.test_actions import palette_data
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    person,
    project,
)


EXAMPLE = """\
Some words about the plan.

- Book the hall
- [x] Pick a date

# Design
1. Draw the **logo**
   with a second line

   - colors
   - [x] fonts
     - serif or not
- [ ] Print the *flyers*

## Later
* Ship it

```
not a to-do
```
"""


class ParserTest(TestCase):
    def sections(self, text):
        return [
            (section.title, [todo.title for todo in section.todos])
            for section in from_text.parse(text).sections
        ]

    def test_headings_become_sections_list_items_todos(self):
        parsed = from_text.parse(EXAMPLE)
        self.assertEqual(
            self.sections(EXAMPLE),
            [
                (None, ["Book the hall", "Pick a date"]),
                ("Design", ["Draw the logo", "Print the flyers"]),
                ("Later", ["Ship it"]),
            ],
        )
        self.assertEqual(parsed.count, 5)
        # The paragraph and the code block
        self.assertEqual(parsed.left_out, 2)

    def test_ticked_items_are_completed(self):
        todos = from_text.parse(EXAMPLE).todos
        self.assertEqual(
            [todo.completed for todo in todos], [False, True, False, False, False]
        )

    def test_what_is_indented_becomes_the_notes_nested_items_a_checklist(self):
        logo = from_text.parse(EXAMPLE).todos[2]
        self.assertEqual(
            logo.notes,
            "with a second line\n\n- [ ] colors\n- [x] fonts\n  - serif or not",
        )
        self.assertEqual((logo.done, logo.total), (1, 2))

    def test_ordered_nested_items_and_deeper_levels(self):
        todo = from_text.parse(
            "- Pack\n  1. tent\n  2. stove\n     * gas\n     * matches\n"
        ).todos[0]
        self.assertEqual(todo.notes, "- [ ] tent\n- [ ] stove\n   * gas\n   * matches")
        self.assertEqual((todo.done, todo.total), (0, 2))

    def test_paragraphs_and_code_in_the_notes_as_written(self):
        todo = from_text.parse(
            "- Pack\n\n  Bring *everything*.\n\n  ```\n  ls -l\n  ```\n"
        ).todos[0]
        self.assertEqual(todo.notes, "Bring *everything*.\n\n```\nls -l\n```")

    def test_a_text_without_list_items_a_todo_per_line(self):
        text = "Book the hall\nPick a **date**\n\n# Later\n\nShip it\n"
        self.assertEqual(
            self.sections(text),
            [(None, ["Book the hall", "Pick a date"]), ("Later", ["Ship it"])],
        )
        self.assertEqual(from_text.parse(text).left_out, 0)

    def test_underlined_headings_and_any_level(self):
        text = "Design\n======\n- Logo\n\n### Launch\n- Party\n\nLater\n---\n- Ship\n"
        self.assertEqual(
            self.sections(text),
            [
                (None, []),
                ("Design", ["Logo"]),
                ("Launch", ["Party"]),
                ("Later", ["Ship"]),
            ],
        )

    def test_the_same_heading_twice_is_one_section(self):
        text = "# Design\n- Logo\n# Launch\n- Party\n#  design \n- Flyers\n"
        self.assertEqual(
            self.sections(text)[1:],
            [("Design", ["Logo", "Flyers"]), ("Launch", ["Party"])],
        )

    def test_long_titles_are_cut_the_line_kept_in_the_notes(self):
        line = "word " * 120
        todo = from_text.parse(f"- {line}\n  more\n").todos[0]
        self.assertLessEqual(len(todo.title), 500)
        self.assertTrue(todo.title.endswith("…"))
        self.assertEqual(todo.notes, f"{line.strip()}\n\nmore")

    def test_titles_are_plain_text(self):
        todo = from_text.parse("- Call [Ada](https://example.com) about `x` ~~y~~\n")
        self.assertEqual(todo.todos[0].title, "Call Ada about x y")

    def test_empty_items_are_left_out(self):
        self.assertEqual(self.sections("- \n- [ ]\n- Real\n"), [(None, ["Real"])])

    def test_crlf(self):
        self.assertEqual(
            self.sections("# A\r\n- one\r\n- two\r\n"),
            [(None, []), ("A", ["one", "two"])],
        )


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project("Pitch", members=[self.ada, self.bob, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.design = ops.create_group(todolist=self.list.todolist, title="Design")
        self.hall = ops.create_todo(
            todolist=self.list, title="Old to-do", creator=self.ada
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )

    def todos(self, todolist=None):
        return sorted(
            Item.objects.filter(
                parent=todolist or self.list, kind=Kind.TODO
            ).select_related("todo", "todo__group"),
            key=lambda t: (
                t.todo.group is not None,
                t.todo.group.position if t.todo.group else 0,
                t.position,
                t.pk,
            ),
        )


class OperationTest(Fixture, TestCase):
    def test_adding(self):
        Event.objects.all().delete()
        plan = ops.add_from_text(self.list, EXAMPLE, actor=self.bob)
        self.assertEqual(plan.count, 5)
        todos = self.todos()
        self.assertEqual(
            [(t.title, t.todo.group and t.todo.group.title) for t in todos],
            [
                ("Old to-do", None),
                ("Book the hall", None),
                ("Pick a date", None),
                ("Draw the logo", "Design"),
                ("Print the flyers", "Design"),
                ("Ship it", "Later"),
            ],
        )
        # "Design" is the existing group, "Later" new at the end
        self.assertEqual(
            [g.title for g in self.list.todolist.groups.all()], ["Design", "Later"]
        )
        by_title = {t.title: t for t in todos}
        self.assertEqual(by_title["Book the hall"].position, 2)
        self.assertIsNotNone(by_title["Pick a date"].todo.completed_at)
        self.assertEqual(by_title["Pick a date"].todo.completed_by, self.bob)
        logo = by_title["Draw the logo"].todo
        self.assertEqual((logo.checklist_done, logo.checklist_total), (1, 2))
        self.assertEqual(by_title["Ship it"].creator, self.bob)

    def test_one_event_silent_todos(self):
        subscribe(self.ada, self.list)
        Event.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_from_text(self.list, "- One\n- Two\n- Three\n", actor=self.bob)
        event = Event.objects.get()
        self.assertEqual(event.action, Action.ADDED_TODOS)
        self.assertEqual(event.item, self.list)
        self.assertEqual(event.data["todos"], 3)
        self.assertTrue(event.is_client_visible)
        # The list's subscribers hear of it once
        self.assertEqual(
            list(Notification.objects.values_list("user", flat=True)),
            [self.ada.pk],
        )
        # The adder follows the to-dos as their creator
        new = [t for t in self.todos() if t != self.hall]
        self.assertEqual(
            Subscription.objects.filter(user=self.bob, item__in=new).count(), 3
        )

    def test_visibility_is_the_lists(self):
        ops.add_from_text(self.list, "- Visible\n", actor=self.ada)
        ops.add_from_text(self.internal, "- Hidden\n", actor=self.ada)
        self.assertTrue(Item.objects.get(title="Visible").is_client_visible)
        self.assertFalse(Item.objects.get(title="Hidden").is_client_visible)
        self.assertFalse(
            Item.objects.visible_to(self.cleo).filter(title="Hidden").exists()
        )

    def test_clients_create_groups_only_in_lists_they_created(self):
        with self.assertRaises(ops.FromTextRefused) as cm:
            ops.add_from_text(self.list, "# New\n- One\n", actor=self.cleo)
        self.assertIn("New", str(cm.exception))
        self.assertEqual(len(self.todos()), 1)
        # Existing groups are fine
        ops.add_from_text(self.list, "# design\n- One\n- Two\n", actor=self.cleo)
        self.assertEqual(
            [t.title for t in self.todos() if t.todo.group == self.design],
            ["One", "Two"],
        )

    def test_limits(self):
        text = "".join(f"- {n}\n" for n in range(501))
        with self.assertRaisesMessage(
            ops.FromTextRefused,
            "This text has 501 to-dos; up to 500 can be added at once.",
        ):
            ops.add_from_text(self.list, text, actor=self.ada)
        with self.assertRaisesMessage(ops.FromTextRefused, "200 KB"):
            ops.add_from_text(self.list, "- x" * 70000, actor=self.ada)
        with self.assertRaisesMessage(ops.FromTextRefused, "no to-dos"):
            ops.add_from_text(self.list, "Just words.\n\n- \n", actor=self.ada)
        self.assertEqual(len(self.todos()), 1)

    def test_not_to_archived_lists(self):
        ops.archive(self.list, actor=self.ada)
        with self.assertRaises(ops.FromTextRefused):
            ops.add_from_text(self.list, "- One\n", actor=self.ada)


class ViewTest(Fixture, TestCase):
    def url(self, item=None):
        return reverse("list_from_text", args=[(item or self.list).pk])

    def test_modal_and_page(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url(), headers=MODAL)
        assert_modal(self, response, title="Add from text…")
        self.assertContains(response, "Paste a text or choose a file.")
        self.assertContains(response, 'data-ready="false"')
        # A plain textarea, not the editor
        self.assertNotContains(response, "data-toolbar")
        assert_page(self, self.client.get(self.url()), title="Add from text…")

    def test_adding_as_staff(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url(),
            {"todolist": self.list.pk, "text": "# Later\n- One\n- Two\n"},
            headers=MODAL,
        )
        assert_modal_redirect(self, response, self.list.get_absolute_url())
        self.assertEqual([t.title for t in self.todos()][1:], ["One", "Two"])

    def test_another_list(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url(), {"todolist": self.internal.pk, "text": "- Elsewhere\n"}
        )
        self.assertRedirects(response, self.internal.get_absolute_url())
        self.assertEqual([t.title for t in self.todos(self.internal)], ["Elsewhere"])

    def test_a_file_without_javascript(self):
        self.client.force_login(self.ada)
        upload = SimpleUploadedFile(
            "plan.md", b"- From the file\n", content_type="text/markdown"
        )
        self.client.post(
            self.url(), {"todolist": self.list.pk, "text": "- Typed\n", "file": upload}
        )
        self.assertEqual(
            [t.title for t in self.todos()][1:], ["Typed", "From the file"]
        )

    def test_other_files_are_refused(self):
        self.client.force_login(self.ada)
        upload = SimpleUploadedFile("a.png", b"\x89PNG", content_type="image/png")
        response = self.client.post(
            self.url(), {"todolist": self.list.pk, "file": upload}
        )
        self.assertContains(response, "Only text files can be added as to-dos.")
        self.assertEqual(len(self.todos()), 1)

    def test_errors_and_the_preview_after_posting(self):
        self.client.force_login(self.ada)
        text = "".join(f"- {n}\n" for n in range(501))
        response = self.client.post(
            self.url(), {"todolist": self.list.pk, "text": text}, headers=MODAL
        )
        self.assertContains(response, "This text has 501 to-dos")
        self.assertEqual(len(self.todos()), 1)

    def test_preview(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("list_from_text_preview", args=[self.list.pk]),
            {"todolist": self.list.pk, "text": EXAMPLE},
        )
        self.assertContains(response, 'data-label="Add 5 to-dos"')
        self.assertContains(response, 'data-ready="true"')
        self.assertContains(response, "Design")
        self.assertContains(response, ">existing<")
        self.assertContains(response, ">new<")
        self.assertContains(response, "1/2")
        self.assertContains(
            response, "2 paragraphs aren’t list items and are left out."
        )
        self.assertEqual(len(self.todos()), 1)

    def test_clients(self):
        self.client.force_login(self.cleo)
        # Internal lists aren't there
        self.assertEqual(self.client.get(self.url(self.internal)).status_code, 404)
        response = self.client.get(self.url(), headers=MODAL)
        assert_modal(self, response, title="Add from text…")
        self.assertNotContains(response, "Internal")
        # New groups only in lists they created
        response = self.client.post(
            reverse("list_from_text_preview", args=[self.list.pk]),
            {"todolist": self.list.pk, "text": "# New\n- One\n"},
        )
        self.assertContains(response, "Only the list’s creator can add groups.")
        self.assertContains(response, 'data-ready="false"')
        response = self.client.post(
            self.url(), {"todolist": self.list.pk, "text": "- One\n"}, headers=MODAL
        )
        assert_modal_redirect(self, response)
        self.assertEqual(Item.objects.get(title="One").creator, self.cleo)
        # Not into the internal list by its ID either
        response = self.client.post(
            self.url(), {"todolist": self.internal.pk, "text": "- Two\n"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="Two").exists())

    def test_the_more_menu_and_the_drop_zone(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.list.get_absolute_url())
        self.assertContains(response, self.url())
        self.assertContains(response, "data-drop-text-page")
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, f'data-drop-text="{self.url()}"')
        ops.archive(self.list, actor=self.ada)
        response = self.client.get(self.list.get_absolute_url())
        self.assertNotContains(response, self.url())
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_palette(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            response = self.client.get(self.list.get_absolute_url())
            actions = {a["label"]: a for a in palette_data(response)["actions"]}
            self.assertEqual(actions["Add from text…"]["url"], self.url())
        ops.archive(self.list, actor=self.ada)
        response = self.client.get(self.list.get_absolute_url())
        labels = {a["label"] for a in palette_data(response)["actions"]}
        self.assertNotIn("Add from text…", labels)

    def test_feed_and_mail(self):
        subscribe(self.ada, self.list)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_from_text(self.list, "- One\n- Two\n", actor=self.bob)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("feed"))
        self.assertContains(response, "added 2 to-dos to")
        event = Event.objects.get(action=Action.ADDED_TODOS)
        self.assertEqual(mails.describe(event, self.ada), "Bob Example added 2 to-dos.")
