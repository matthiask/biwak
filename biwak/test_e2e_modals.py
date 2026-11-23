"""Forms in a modal in the browser (biwak/modals.py, frontend/modal.js):
opening, saving, errors, Escape and the focus"""

import re

from django.urls import reverse

from biwak.accounts.models import User
from biwak.activity.models import (
    Action,
    Event,
    LevelOverride,
    Notification,
    Subscription,
)
from biwak.activity.operations import unsubscribe
from biwak.items import operations as ops
from biwak.items.models import Item, Kind, Status
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
        self.goto(page, "/projects/")
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
        page.keyboard.press("ControlOrMeta+k")
        page.locator("#wb-palette-input").fill("New list")
        page.locator("#wb-palette-list [role=option]").first.press("Enter")
        expect(page.get_by_role("dialog", name="New list")).to_be_visible()
        self.assertEqual(self.errors, [])


class VisibilityModalTest(E2ETestCase):
    def test_showing_to_clients_asks_first_hiding_doesnt(self):
        todolist = self.make_list(todos=["Order the tent"])
        page = self.page
        self.goto(page, todolist)
        more = page.locator(".wb-page-actions summary", has_text="More")
        link = page.get_by_role("link", name="Show to clients…")

        def open_menu():
            # The switch is in the "More" menu only (decided 2026-11-22)
            if not link.is_visible():
                more.click()

        expect(link).to_be_hidden()
        open_menu()
        link.click()
        dialog = page.get_by_role("dialog", name="Show this list to clients?")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text(
            "Makes this list, 1 to-do and 0 comments visible to 1 client."
        )
        self.assertEqual(dialog.locator("nav").count(), 0)
        # Cancel changes nothing
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        todolist.refresh_from_db()
        self.assertFalse(todolist.visible_to_clients)
        # Escape too
        open_menu()
        link.click()
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        todolist.refresh_from_db()
        self.assertFalse(todolist.visible_to_clients)
        # Confirming shows it, and now the menu offers one click to hide it
        open_menu()
        link.click()
        dialog.get_by_role("button", name="Show to clients").click()
        expect(page.get_by_text("Clients can see this.")).to_be_visible()
        todolist.refresh_from_db()
        self.assertTrue(todolist.visible_to_clients)
        more.click()
        page.get_by_role("button", name="Hide from clients").click()
        expect(page.get_by_text("Clients can see this.")).to_be_hidden()
        more.click()
        expect(link).to_be_visible()
        todolist.refresh_from_db()
        self.assertFalse(todolist.visible_to_clients)
        self.assertEqual(self.errors, [])


class GroupModalsTest(E2ETestCase):
    def test_new_group_and_editing_it(self):
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

        # The group's menu has the modal, which closes the menu
        menu = page.locator("details.wb-menu:has(.wb-group-menu)").first
        menu.locator("summary").click()
        menu.get_by_role("link", name="Edit the group").click()
        dialog = page.get_by_role("dialog", name="Edit the group")
        expect(dialog.locator("[name=title]")).to_have_value("Later")
        self.assertFalse(menu.evaluate("el => el.open"))
        dialog.locator("[name=title]").fill("Next week")
        dialog.get_by_label("Forest").check()
        dialog.get_by_role("button", name="Save").click()
        expect(page.locator(".wb-group-name", has_text="Next week")).to_be_visible()
        expect(
            page.locator("section.wb-group", has_text="Next week")
        ).to_have_attribute("data-group-color", "forest")
        self.assertEqual(
            list(todolist.todolist.groups.values_list("title", "color")),
            [("Next week", "forest"), ("Soon", "")],
        )

        # Escape: the focus goes back to the menu's button
        menu.locator("summary").click()
        menu.get_by_role("link", name="Edit the group").click()
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


def saved(response):
    """The choice's POST answered (its redirect: saved)"""
    return response.request.method == "POST" and "/notify/" in response.url


class MemberNotificationsTest(E2ETestCase):
    """A project's people page: a member's notifications are a select in
    the row saving itself, removing a button in the row asking first
    (decided 2026-11-22), staff for anybody, a client for themselves"""

    def test_staff_change_a_client_s(self):
        from biwak.projects import operations as project_ops

        page = self.page
        self.goto(page, f"/projects/{self.project.pk}/people/")
        page.evaluate("window.marker = 1")
        select = page.get_by_label("Notifications of Cleo Example")
        expect(select).to_have_value("default")
        # No Save with JavaScript
        row = page.locator(f"#member-{self.cleo.pk}")
        expect(row.get_by_role("button", name="Save")).to_be_hidden()
        # Disabled while it saves: the answer waits until it's seen
        held = []

        def hold(route):
            # A function, not ``held.append``: Playwright wraps the handler
            held.append(route)

        page.route("**/notify/", hold)
        select.focus()  # As a click or Tab would
        select.select_option("tagged")
        expect(select).to_be_disabled()
        self.assertEqual(len(held), 1)
        held[0].continue_()
        expect(select).to_be_enabled()
        self.assertEqual(project_ops.notify_choice(self.cleo, self.project), "tagged")
        # No reload, the new value, the focus stays on the select
        expect(select).to_have_value("tagged")
        expect(select).to_be_focused()
        self.assertEqual(page.evaluate("window.marker"), 1)
        page.unroute("**/notify/")
        with page.expect_response(saved):
            select.select_option("default")
        expect(select).to_be_enabled()
        self.assertEqual(project_ops.notify_choice(self.cleo, self.project), "default")
        self.assertEqual(self.errors, [])

    def test_a_failed_save_shakes_and_goes_back(self):
        from biwak.projects import operations as project_ops

        page = self.page
        self.watch_classes(page)
        self.goto(page, f"/projects/{self.project.pk}/people/")
        select = page.get_by_label("Notifications of Cleo Example")
        for name, fail in [
            ("an error", lambda route: route.fulfill(status=500, body="Broken")),
            ("no connection", lambda route: route.abort()),
        ]:
            with self.subTest(name):
                page.route("**/notify/", fail)
                select.focus()
                select.select_option("tagged")
                self.seen_class(page, "wb-shake")
                # The stored value again, usable, still focused
                expect(select).to_have_value("default")
                expect(select).to_be_enabled()
                expect(select).to_be_focused()
                page.unroute("**/notify/")
                page.evaluate("window.seenClasses.clear()")
        # Without motion it goes back without shaking
        page.emulate_media(reduced_motion="reduce")
        page.route("**/notify/", lambda route: route.abort())
        select.select_option("tagged")
        expect(select).to_have_value("default")
        expect(select).to_be_enabled()
        self.never_class(page, "wb-shake")
        self.assertEqual(project_ops.notify_choice(self.cleo, self.project), "default")
        # The browser logs the failed requests
        self.errors.clear()

    def test_staff_remove_after_a_question(self):
        page = self.page
        self.goto(page, f"/projects/{self.project.pk}/people/")
        remove = page.get_by_role("link", name="Remove Cleo Example from the project")
        remove.click()
        dialog = page.get_by_role(
            "dialog", name=f"Remove Cleo Example from {self.project.name}?"
        )
        # Cancel keeps them
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        self.assertTrue(self.project.is_member(self.cleo))
        remove.click()
        dialog.get_by_role("button", name="Remove").click()
        expect(dialog).to_be_hidden()
        expect(remove).to_have_count(0)
        self.assertFalse(self.project.is_member(self.cleo))
        self.assertEqual(self.errors, [])

    def test_a_client_changes_only_their_own(self):
        from biwak.projects import operations as project_ops

        page = self.login(self.cleo)
        self.goto(page, f"/projects/{self.project.pk}/people/")
        expect(page.locator("select[name=notify]")).to_have_count(1)
        # No removing, not even themselves (decided 2026-11-22)
        expect(page.get_by_role("link", name=re.compile("^Remove"))).to_have_count(0)
        with page.expect_response(saved):
            page.get_by_label("Your notifications").select_option("tagged")
        self.assertEqual(project_ops.notify_choice(self.cleo, self.project), "tagged")
        self.assertEqual(self.errors, [])


class MoreMenuModalTest(E2ETestCase):
    """The "More" menu's forms in the dialog (frontend/modal.js)"""

    def setUp(self):
        super().setUp()
        self.todolist = self.make_list("Launch", visible=True, todos=["Plan"])
        self.make_list("Other")

    def open_more(self, page, entry):
        page.locator("details.wb-menu", has_text="More").first.locator(
            "summary"
        ).click()
        page.get_by_role("link", name=entry).click()
        dialog = page.locator("dialog#modal")
        expect(dialog).to_be_visible()
        return dialog

    def test_notifications_open_save_and_focus_returns(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        expect(dialog.locator("h1")).to_have_text("Notifications for this list")
        # No navigation: the page is still the list's
        self.assertEqual(
            page.url, f"{self.live_server_url}{self.todolist.get_absolute_url()}"
        )
        dialog.get_by_label("Only what concerns me").check()
        dialog.get_by_role("button", name="Save").click()
        expect(page.locator("dialog#modal[open]")).to_have_count(0)
        self.assertEqual(
            LevelOverride.objects.get(user=self.ada, item=self.todolist).level,
            "concerns_me",
        )

    def test_escape_closes_an_unchanged_form_and_returns_the_focus(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(
            page.locator("details.wb-menu", has_text="More").first.locator("summary")
        ).to_be_focused()

    def test_trashing_asks_first(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Move to trash")
        expect(dialog.locator("h1")).to_have_text("Move to the trash?")
        dialog.get_by_role("button", name="Cancel").click()
        self.todolist.refresh_from_db()
        self.assertEqual(self.todolist.status, Status.ACTIVE)
        dialog = self.open_more(page, "Move to trash")
        dialog.get_by_role("button", name="Move to the trash").click()
        page.wait_for_url(f"**{self.project.get_absolute_url()}")
        self.todolist.refresh_from_db()
        self.assertEqual(self.todolist.status, Status.TRASHED)

    def test_moving_a_todo(self):
        todo = Item.objects.get(title="Plan")
        other = Item.objects.get(title="Other")
        page = self.page
        self.goto(page, todo)
        dialog = self.open_more(page, "Move to…")
        dialog.locator("select").first.select_option(label="Other")
        # The redirect loads the page again
        with page.expect_navigation():
            dialog.get_by_role("button", name="Move", exact=True).click()
        todo.refresh_from_db()
        self.assertEqual(todo.parent_id, other.pk)

    def test_a_modifier_key_leaves_the_link_alone(self):
        page = self.page
        self.goto(page, self.todolist)
        page.locator("details.wb-menu", has_text="More").first.locator(
            "summary"
        ).click()
        self.assertFalse(self.modifier_click_is_prevented(page, "a[data-modal]"))
        expect(page.locator("dialog#modal[open]")).to_have_count(0)

    def modifier_click_is_prevented(self, page, selector):
        """Whether the page's scripts took a Ctrl+click on ``selector``
        (the browser would follow the link into a new tab otherwise)"""
        return page.evaluate(
            """(selector) => {
                let prevented = null
                window.addEventListener("click", (event) => {
                    prevented = event.defaultPrevented
                    event.preventDefault()
                }, { once: true })
                document.querySelector(selector).dispatchEvent(
                    new MouseEvent("click", {
                        bubbles: true, cancelable: true, ctrlKey: true, button: 0,
                    })
                )
                return prevented
            }""",
            selector,
        )

    def test_new_list_from_the_palette_and_members(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("ControlOrMeta+k")
        page.get_by_role("combobox").fill("New list")
        page.keyboard.press("Enter")
        dialog = page.locator("dialog#modal")
        expect(dialog.locator("h1")).to_have_text("New list")
        # Errors stay in the dialog (blanks pass the browser's check)
        dialog.get_by_label("title").fill("   ")
        dialog.get_by_role("button", name="Add list").click()
        expect(dialog.locator(".invalid-feedback")).to_be_visible()
        expect(dialog.locator("h1")).to_have_text("New list")
        dialog.get_by_label("title").fill("Fresh")
        dialog.get_by_role("button", name="Add list").click()
        page.wait_for_url("**/lists/**")
        self.assertTrue(Item.objects.filter(title="Fresh").exists())

        self.goto(page, reverse("project_people", args=[self.project.pk]))
        page.get_by_role("link", name="Invite by email").click()
        dialog = page.locator("dialog#modal")
        # The form inviting several people (specs/activation.md, "Inviting")
        expect(dialog.locator("h1")).to_have_text("Invite people")
        dialog.get_by_label("Email").first.fill("dora@example.org")
        dialog.get_by_role("button", name="Invite").click()
        # Listed: their mark links to their page, the email below the name
        # (named by the address: no name was given)
        expect(
            page.locator("div.small", has_text="dora@example.org").first
        ).to_be_visible()
        dora = User.objects.get(email="dora@example.org")
        expect(
            page.locator(f"a.wb-person-link[href='/people/{dora.pk}/']")
        ).to_be_visible()
