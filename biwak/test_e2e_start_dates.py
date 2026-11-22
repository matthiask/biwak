"""Start dates in the browser: the field showing once the due date is set
(frontend/start-date.js) and the collapsed "Starting later"
(specs/start-dates.md)"""

import datetime as dt

from biwak import schedules
from biwak.items import operations as ops
from biwak.items.models import Item, Todo
from biwak.test_e2e import E2ETestCase, expect


class StartDateFieldTest(E2ETestCase):
    def test_the_inline_form(self):
        todolist = self.make_list(visible=True)
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        starts = add.locator("[name=starts_on]")
        expect(starts).to_be_hidden()
        add.locator("[name=due_on]").fill("2026-12-07")
        expect(starts).to_be_visible()
        expect(starts).to_have_attribute("max", "2026-12-07")
        starts.fill("2026-12-03")
        add.locator("[name=title]").fill("Book the hall")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        row = page.locator("[data-todo]").filter(has_text="Book the hall")
        expect(row).to_contain_text("3–7 Dec")
        # Ready for the next one: no due date, no start date to see
        expect(add.locator("[name=due_on]")).to_have_value("")
        expect(starts).to_be_hidden()
        todo = Item.objects.get(title="Book the hall").todo
        self.assertEqual(str(todo.starts_on), "2026-12-03")
        self.assertEqual(self.errors, [])

    def test_the_edit_form_as_a_client(self):
        todolist = self.make_list(visible=True)
        item = ops.create_todo(
            todolist=todolist, title="Pitch the tent", creator=self.ada
        )
        page = self.login(self.cleo)
        self.goto(page, item)
        page.locator("[data-edit-focus=due_on]").click()
        form = page.locator("#live-text form[data-view-edit-form]")
        starts = form.locator("[name=starts_on]")
        expect(form.locator("[name=due_on]")).to_be_visible()
        expect(starts).to_be_hidden()
        form.locator("[name=due_on]").fill("2026-12-07")
        expect(starts).to_be_visible()
        starts.fill("2026-12-04")
        form.get_by_role("button", name="Save").click()
        expect(page.locator("#live-text .wb-facts")).to_contain_text("Starts on")
        todo = Todo.objects.get(pk=item.pk)
        self.assertEqual(str(todo.starts_on), "2026-12-04")
        self.assertEqual(self.errors, [])


class StartingLaterTest(E2ETestCase):
    def test_collapsed_until_opened(self):
        today = schedules.today()
        todolist = self.make_list(visible=True)
        for title, starts in [("Pack now", None), ("Pack later", 3)]:
            ops.create_todo(
                todolist=todolist,
                title=title,
                creator=self.ada,
                due_on=today + dt.timedelta(days=5),
                starts_on=starts and today + dt.timedelta(days=starts),
                assignees=[self.ada, self.cleo],
            )
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                page = self.login(user)
                for url in ["/todos/", "/"]:
                    self.goto(page, url)
                    later = page.locator("[data-starting-later]")
                    expect(later.locator("summary")).to_have_text("Starting later (1)")
                    expect(
                        page.locator("a.wb-todo-title", has_text="Pack now")
                    ).to_be_visible()
                    expect(
                        page.locator("a.wb-todo-title", has_text="Pack later")
                    ).to_be_hidden()
                    later.locator("summary").click()
                    expect(
                        page.locator("a.wb-todo-title", has_text="Pack later")
                    ).to_be_visible()
        self.assertEqual(self.errors, [])
