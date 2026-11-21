"""Forms in a modal in the browser (biwak/modals.py, frontend/modal.js):
opening, saving, errors, Escape and the focus"""

from biwak.accounts.models import User
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.activity.operations import unsubscribe
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.projects.models import Project
from biwak.test_e2e import E2ETestCase, expect
from biwak.test_utils import person


class ModalTest(E2ETestCase):
    def test_new_list(self):
        page = self.page
        self.goto(page, self.project)
        button = page.get_by_role("link", name="New list")
        button.click()
        dialog = page.get_by_role("dialog", name="New list")
        expect(dialog).to_be_visible()
        expect(dialog.locator("[name=title]")).to_be_focused()
        # No page around the form, and the page's own URL didn't change
        self.assertEqual(dialog.locator("nav").count(), 0)
        self.assertTrue(page.url.endswith(f"/projects/{self.project.pk}/"))

        # Errors: the form again in the dialog
        dialog.locator("[name=title]").fill("   ")
        dialog.get_by_role("button", name="Add list").click()
        expect(dialog.get_by_text("This field is required.")).to_be_visible()
        expect(dialog).to_be_visible()

        dialog.locator("[name=title]").fill("Launch plan")
        dialog.get_by_role("button", name="Add list").click()
        page.wait_for_url("**/lists/*/")
        item = Item.objects.get(kind=Kind.LIST, title="Launch plan")
        self.assertTrue(page.url.endswith(item.get_absolute_url()))
        self.assertEqual(self.errors, [])

    def test_new_project_from_organizations(self):
        """Two steps in the dialog (specs/organizations.md): the
        organizations involved, then their people, staff and invitations"""
        page = self.page
        self.goto(page, "/")
        page.get_by_role("link", name="New project").click()
        dialog = page.get_by_role("dialog", name="New project")
        expect(dialog).to_be_visible()
        dialog.locator("[name=name]").fill("Camp")
        dialog.get_by_label("Example Client Ltd").check()
        dialog.get_by_role("button", name="Continue").click()
        people = dialog.get_by_label("Cleo Example, Example Client Ltd")
        expect(people).to_be_checked()
        dialog.get_by_label("Bob Example").check()
        dialog.locator("[name=invite-0-email]").fill("dora@example.org")
        dialog.get_by_role("button", name="Add project").click()
        page.wait_for_url("**/projects/*/")
        project = Project.objects.get(name="Camp")
        self.assertTrue(page.url.endswith(project.get_absolute_url()))
        self.assertEqual(
            {m.user.email for m in project.memberships.all()},
            {
                "ada@example.org",
                "bob@example.org",
                "cleo@example.org",
                "dora@example.org",
            },
        )
        dora = User.objects.get(email="dora@example.org")
        self.assertEqual(dora.organization.name, "Example Client Ltd")
        self.assertEqual(self.errors, [])

    def test_escape_and_the_focus(self):
        """Escape closes an unchanged form, a changed one needs it twice;
        the focus goes back to the link"""
        page = self.page
        self.goto(page, self.project)
        button = page.get_by_role("link", name="New list")
        button.focus()
        button.press("Enter")
        dialog = page.get_by_role("dialog", name="New list")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(button).to_be_focused()

        button.click()
        field = dialog.locator("[name=title]")
        expect(field).to_be_focused()
        field.fill("Half")
        page.keyboard.press("Escape")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(button).to_be_focused()
        self.assertFalse(Item.objects.filter(kind=Kind.LIST).exists())

        # Cancel closes it too
        button.click()
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_a_modifier_key_opens_the_page(self):
        page = self.page
        self.goto(page, self.project)
        # A new window, with the form's own page
        with page.context.expect_page() as opened:
            page.get_by_role("link", name="New list").click(modifiers=["Shift"])
        popup = opened.value
        popup.wait_for_load_state()
        self.assertTrue(popup.url.endswith("/lists/new/"))
        expect(popup.get_by_role("heading", name="New list")).to_be_visible()

    def test_the_palette_opens_the_modal(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("Control+k")
        page.locator("#wb-palette-input").fill("New list")
        page.locator("#wb-palette-list [role=option]").first.press("Enter")
        expect(page.get_by_role("dialog", name="New list")).to_be_visible()
        self.assertEqual(self.errors, [])


class GroupModalsTest(E2ETestCase):
    def test_new_group_and_renaming_it(self):
        todolist = self.make_list(groups=["Later"])
        page = self.page
        self.goto(page, todolist)
        page.get_by_role("link", name="New group").click()
        dialog = page.get_by_role("dialog", name="New group")
        expect(dialog.locator("[name=title]")).to_be_focused()
        dialog.locator("[name=title]").fill("Soon")
        dialog.get_by_role("button", name="Add group").click()
        expect(page.locator(".wb-group-name", has_text="Soon")).to_be_visible()
        expect(dialog).to_be_hidden()

        # The pencil's menu has the modal, which closes the menu
        menu = page.locator("details.wb-menu:has(.wb-group-menu)").first
        menu.locator("summary").click()
        menu.get_by_role("link", name="Rename the group").click()
        dialog = page.get_by_role("dialog", name="Rename the group")
        expect(dialog.locator("[name=title]")).to_have_value("Later")
        self.assertFalse(menu.evaluate("el => el.open"))
        dialog.locator("[name=title]").fill("Next week")
        dialog.get_by_role("button", name="Rename").click()
        expect(page.locator(".wb-group-name", has_text="Next week")).to_be_visible()
        self.assertEqual(
            list(todolist.todolist.groups.values_list("title", flat=True)),
            ["Next week", "Soon"],
        )

        # Escape: the focus goes back to the menu's button
        menu.locator("summary").click()
        menu.get_by_role("link", name="Rename the group").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_be_hidden()
        expect(menu.locator("summary")).to_be_focused()
        self.assertEqual(self.errors, [])


class SubscribersTest(E2ETestCase):
    """The subscribers modal (specs/subscribers.md): the picker of the
    assignees, "Tell them now" with a note"""

    def setUp(self):
        super().setUp()
        self.dora = person("Dora")  # Staff, not a member
        self.todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.todolist, title="Order the tent", creator=self.ada
        )

    def open_modal(self, page):
        self.goto(page, self.todo)
        page.get_by_role("link", name="Manage…").click()
        dialog = page.get_by_role("dialog", name="Subscribers")
        expect(dialog).to_be_visible()
        return dialog

    def pick(self, dialog, name):
        dialog.locator(".wb-picker-input").click()
        dialog.locator(".wb-picker-list li", has_text=name).click()

    def test_adding_people_and_telling_them_now(self):
        page = self.page
        dialog = self.open_modal(page)
        expect(dialog.locator("[data-subscribers]")).to_contain_text("Ada")
        self.pick(dialog, "Cleo")
        self.pick(dialog, "Dora")
        expect(dialog.locator(".wb-pill")).to_have_count(2)
        # Picked people aren't offered again
        dialog.locator(".wb-picker-input").click()
        expect(dialog.locator(".wb-picker-list li", has_text="Cleo")).to_have_count(0)
        page.keyboard.press("Escape")
        expect(dialog.locator(".wb-picker-list")).to_be_hidden()
        dialog.get_by_label("Tell them now").check()
        dialog.get_by_label("Note").fill("Have a look")
        dialog.get_by_role("button", name="Add").click()
        # The page loads again, the subscribers box has them
        expect(page.locator(".wb-person-link", has_text="Dora")).to_be_visible()
        subscribers = {
            s.user.get_short_name()
            for s in Subscription.objects.filter(item=self.todo, added_by=self.ada)
        }
        self.assertEqual(subscribers, {"Cleo", "Dora"})
        event = Event.objects.get(action=Action.SHARED)
        self.assertEqual(event.data["note"], "Have a look")
        self.assertEqual(Notification.objects.filter(event=event).count(), 2)
        self.assertEqual(self.errors, [])

    def test_saving_without_anybody_shows_the_error(self):
        dialog = self.open_modal(self.page)
        dialog.get_by_role("button", name="Add").click()
        expect(dialog.get_by_text("Pick at least one person.")).to_be_visible()
        self.assertFalse(Subscription.objects.filter(added_by=self.ada))

    def test_a_client_is_offered_only_the_members(self):
        unsubscribe(self.ada, self.todo)
        page = self.login(self.cleo)
        self.goto(page, self.todo)
        page.get_by_role("link", name="Manage…").click()
        dialog = page.get_by_role("dialog", name="Subscribers")
        expect(dialog).to_be_visible()
        dialog.locator(".wb-picker-input").click()
        names = dialog.locator(".wb-picker-list li").all_inner_texts()
        self.assertEqual(len(names), 1)
        self.assertIn("Ada", names[0])
        self.assertEqual(self.errors, [])
