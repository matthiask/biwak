"""Pages in view mode with click to edit (specs/ui.md, "Click to edit"): the
to-do, the message, the file and the check-in answer show the item, the
form comes in place of the text (htmx) or as the page's own form; the
editing marker is set only while the form is shown; the assignee picker
and the rule widget's end fields."""

import re

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from biwak import checklists
from biwak.checkins.models import Answer
from biwak.items import editing, operations as ops
from biwak.items.models import Editing
from biwak.projects import operations as project_ops
from biwak.test_utils import check_in_answers, person, project, tags


HTMX = {"HX-Request": "true", "HX-Target": "live-text"}


class ViewModeBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.todolist = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.todolist,
            title="Order the tent",
            creator=self.ada,
            notes="Two *poles*\n\n- [ ] Pegs",
            due_on="2027-03-01",
            assignees=[self.ada],
            recurrence="FREQ=WEEKLY;BYDAY=MO",
        )
        self.url = self.todo.get_absolute_url()
        self.edit = reverse("todo_edit", args=[self.todo.pk])
        self.client.force_login(self.ada)

    def version(self):
        self.todo.refresh_from_db()
        return checklists.text_hash(ops.text_of(self.todo))

    def marker(self, user=None):
        return Editing.objects.filter(item=self.todo, user=user or self.ada).exists()


class TodoViewTest(ViewModeBase):
    def test_the_page_shows_the_to_do_not_a_form(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            page = self.client.get(self.url)
            self.assertNotContains(page, 'name="notes"')
            self.assertNotContains(page, "data-view-form")
            self.assertContains(page, "Assigned to")
            self.assertContains(page, "Ada")
            self.assertContains(page, "Monday, 1. March 2027")
            self.assertContains(page, "Every Monday")
            self.assertContains(page, "<em>poles</em>")
            # The title once, as the heading
            self.assertContains(page, "Order the tent", count=2)
            self.assertContains(page, f'data-edit-url="{self.edit}"')
            self.assertContains(page, f'href="{self.edit}"')

    def test_the_facts_and_the_notes_share_one_card(self):
        # Reactions and comments are below it, the sidebar beside it
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            html = self.client.get(self.url).content.decode()
            # The card, whatever its other classes and attributes
            start = re.search(
                r'<div(?=[^>]*class="[^"]*\bcard\b)(?=[^>]*data-edit-url)', html
            ).start()
            card = html[start : html.index("Subscribers", start)]
            self.assertIn("Assigned to", card)
            self.assertIn("<hr", card)
            self.assertIn("<em>poles</em>", card)
            self.assertLess(card.index("Assigned to"), card.index("<hr"))
            self.assertLess(card.index("<hr"), card.index("<em>poles</em>"))
            # One card from the facts to the notes, not one each
            notes = card.index("<em>poles</em>")
            self.assertEqual(len(tags(card[:notes], cls="card")), 1)
            self.assertNotIn("Comments", card[: card.index("<em>poles</em>")])

    def test_the_form_in_place_sits_in_a_card_too(self):
        response = self.client.get(self.edit, headers=HTMX)
        self.assertTrue(tags(response.content.decode(), cls="card"))

    def test_the_view_sets_no_marker(self):
        self.client.get(self.url)
        self.assertFalse(self.marker())

    def test_ticking_works_in_the_view(self):
        page = self.client.get(self.url)
        self.assertContains(page, "task-list-item-checkbox")
        response = self.client.post(
            reverse("item_tick", args=[self.todo.pk]),
            {"index": 0, "checked": 1, "version": self.version()},
        )
        self.assertEqual(response.status_code, 200)
        self.todo.todo.refresh_from_db()
        self.assertIn("[x] Pegs", self.todo.todo.notes)

    def test_the_form_page(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            page = self.client.get(self.edit)
            self.assertContains(page, 'name="title"')
            self.assertContains(page, 'name="notes"')
            self.assertContains(page, 'name="assignees"')
            self.assertContains(page, "data-view-form")
            # A page of its own: a plain form, the plain Cancel
            self.assertNotContains(page, f'hx-post="{self.edit}"')
            self.assertContains(page, f'href="{self.url}"')
            self.assertTrue(self.marker(user))

    def test_the_form_in_place_posts_with_htmx(self):
        page = self.client.get(self.edit, headers=HTMX)
        self.assertContains(page, f'hx-post="{self.edit}"')
        self.assertContains(page, 'hx-select="#live-text"')
        self.assertContains(page, 'hx-select-oob="#live-header"')
        self.assertContains(page, f'hx-get="{self.url}"')
        self.assertContains(page, 'id="live-text"')

    def test_the_marker_lasts_while_the_form_is_shown(self):
        self.client.get(self.edit)
        self.assertTrue(self.marker())
        # Cancelling (frontend/editing.js) releases it
        self.client.post(reverse("item_editing", args=[self.todo.pk]), {"release": 1})
        self.assertFalse(self.marker())
        # Saving ends it too
        self.client.get(self.edit)
        response = self.client.post(
            self.edit,
            {
                "form": "todo",
                "title": "Order two tents",
                "notes": "",
                "recurrence_frequency": "",
            },
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(self.marker())
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Order two tents")

    def test_errors_show_the_form_again(self):
        response = self.client.post(
            self.edit, {"form": "todo", "title": ""}, headers=HTMX
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertContains(response, 'name="title"')
        self.assertTrue(self.marker())

    def test_a_stale_save_says_who(self):
        base = editing.version(self.todo)
        ops.update_todo(self.todo, actor=self.ada, title="Order the big tent")
        response = self.client.post(
            self.edit,
            {"form": "todo", "title": "Mine", "base": base},
            headers=HTMX,
        )
        self.assertContains(response, "changed this")
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Order the big tent")

    def test_the_old_posts_to_the_page_still_work(self):
        response = self.client.post(
            self.url, {"form": "todo", "title": "Renamed", "recurrence_frequency": ""}
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Renamed")

    def test_clients_get_404_for_internal_to_dos(self):
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        secret = ops.create_todo(todolist=internal, title="Budget", creator=self.ada)
        self.client.force_login(self.cleo)
        for url in [
            secret.get_absolute_url(),
            reverse("todo_edit", args=[secret.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.get(url, headers=HTMX).status_code, 404)

    def test_the_form_has_the_regions_live_updates_take(self):
        page = self.client.get(self.edit)
        for region in ["live-header", "live-text", "live-comments"]:
            self.assertContains(page, f'id="{region}"')
        # Reactions sit right under the text, before the comments
        content = self.client.get(self.url).content.decode()
        self.assertLess(
            content.index('id="live-text"'), content.index("reactions-item-")
        )
        self.assertLess(
            content.index("reactions-item-"), content.index('id="live-comments"')
        )


class RepeatEndsTest(ViewModeBase):
    def test_the_end_fields_are_inside_the_rule_widgets_fieldset(self):
        page = self.client.get(self.edit).content.decode()
        start = page.index('<fieldset\n  class="wb-rule"')
        end = page.index("</fieldset>", page.index("data-rule-ends"))
        fieldset = page[start:end]
        for name in ["recurrence_ends_on", "recurrence_count"]:
            self.assertEqual(page.count(f'name="{name}"'), 1)
            self.assertIn(f'name="{name}"', fieldset)

    def test_the_ends_keep_their_values_and_save(self):
        todo = ops.update_todo(
            self.todo,
            actor=self.ada,
            recurrence_ends_on="2027-06-01",
            recurrence_count=4,
        )
        page = self.client.get(self.edit)
        self.assertContains(page, 'value="2027-06-01"')
        self.assertContains(page, 'name="recurrence_count"')
        self.assertContains(page, 'value="4"')
        response = self.client.post(
            self.edit,
            {
                "form": "todo",
                "title": "Order the tent",
                "recurrence_frequency": "weekly",
                "recurrence_interval": "1",
                "recurrence_weekdays": ["MO"],
                "recurrence_ends_on": "2027-07-01",
                "recurrence_count": "3",
            },
        )
        self.assertEqual(response.status_code, 302)
        todo.todo.refresh_from_db()
        self.assertEqual(str(todo.todo.recurrence_ends_on), "2027-07-01")
        self.assertEqual(todo.todo.recurrence_count, 3)

    def test_the_view_says_when_it_ends(self):
        ops.update_todo(
            self.todo,
            actor=self.ada,
            recurrence_ends_on="2027-06-01",
            recurrence_count=4,
        )
        page = self.client.get(self.url)
        self.assertContains(page, "Until 1. June 2027.")
        self.assertContains(page, "4 more to come.")

    def test_a_bound_form_shows_what_was_posted(self):
        response = self.client.post(
            self.edit,
            {
                "form": "todo",
                "title": "",
                "recurrence_frequency": "daily",
                "recurrence_interval": "1",
                "recurrence_count": "7",
            },
        )
        self.assertContains(response, 'value="7"')

    def test_the_inline_form_has_them_once_per_group(self):
        group = ops.create_group(todolist=self.todolist.todolist, title="Later")
        page = self.client.get(self.todolist.get_absolute_url()).content.decode()
        self.assertEqual(page.count('name="recurrence_ends_on"'), 2)
        self.assertEqual(page.count('name="recurrence_count"'), 2)
        self.assertEqual(page.count("data-rule-ends"), 2)
        self.assertNotIn("data-repeat-ends", page)
        self.assertTrue(group)

    def test_the_question_form_has_none(self):
        question = check_in_answers(self.project, [self.ada])[0].parent
        page = self.client.get(reverse("question_edit", args=[question.pk]))
        self.assertNotContains(page, "data-rule-ends")


class AssigneePickerTest(ViewModeBase):
    def setUp(self):
        super().setUp()
        # Staff who isn't a member of the project
        self.dora = person("Dora")
        self.cleo2 = person("Dana", client=True)

    def options(self, page):
        content = page.content.decode()
        start = content.index('name="assignees"')
        end = content.index("</select>", start)
        return content[start:end]

    def test_the_select_stays_with_members_first(self):
        page = self.client.get(self.edit)
        self.assertContains(page, "data-assignee-picker")
        self.assertContains(page, "<select")
        options = self.options(page)
        self.assertLess(options.index("Ada"), options.index("Bob"))
        self.assertIn('data-member="true"', options)
        self.assertIn('data-member="false"', options)
        self.assertIn("multiple", page.content.decode())

    def test_clients_only_get_members(self):
        self.client.force_login(self.cleo)
        options = self.options(self.client.get(self.edit))
        self.assertIn("Ada", options)
        self.assertIn("Cleo", options)
        self.assertNotIn("Bob", options)
        self.assertNotIn("Dora", options)
        self.assertNotIn('data-member="false"', options)

    def test_the_inline_form_uses_the_same_select(self):
        page = self.client.get(self.todolist.get_absolute_url())
        self.assertContains(page, "data-assignee-picker")
        self.assertRegex(
            page.content.decode(), r'<select\s+name="assignees"\s+multiple'
        )
        self.assertNotContains(page, 'type="checkbox" name="assignees"')
        self.client.force_login(self.cleo)
        page = self.client.get(self.todolist.get_absolute_url())
        self.assertNotContains(page, "Bob")

    def test_assigning_a_non_member_makes_them_a_member(self):
        self.assertFalse(self.project.memberships.filter(user=self.bob).exists())
        response = self.client.post(
            self.edit,
            {
                "form": "todo",
                "title": "Order the tent",
                "assignees": [self.ada.pk, self.bob.pk],
                "recurrence_frequency": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.ada, self.bob})
        self.assertTrue(self.project.memberships.filter(user=self.bob).exists())

    def test_a_client_cant_assign_non_members(self):
        self.client.force_login(self.cleo)
        response = self.client.post(
            self.edit,
            {
                "form": "todo",
                "title": "Order the tent",
                "assignees": [self.bob.pk],
                "recurrence_frequency": "",
            },
        )
        self.assertContains(response, "valid choice")
        self.assertNotIn(self.bob, self.todo.todo.assignees.all())

    def test_removing_all_assignees(self):
        self.client.post(
            self.edit,
            {"form": "todo", "title": "Order the tent", "recurrence_frequency": ""},
        )
        self.assertEqual(self.todo.todo.assignees.count(), 0)


class MessageViewTest(ViewModeBase):
    def setUp(self):
        super().setUp()
        self.message = ops.create_message(
            project=self.project,
            title="News",
            content="Hello *camp*\n\n- [ ] Pack",
            creator=self.ada,
            visible=True,
        )
        self.url = self.message.get_absolute_url()
        self.edit = reverse("message_edit", args=[self.message.pk])

    def test_the_page_is_clickable_for_who_may_change_it(self):
        page = self.client.get(self.url)
        self.assertContains(page, f'data-edit-url="{self.edit}"')
        self.assertContains(page, 'data-edit-focus="content"')
        self.assertNotContains(page, "data-view-form")
        self.client.force_login(self.cleo)
        page = self.client.get(self.url)
        self.assertNotContains(page, "data-edit-url")
        self.assertEqual(self.client.get(self.edit).status_code, 403)

    def test_the_form_in_place(self):
        page = self.client.get(self.edit, headers=HTMX)
        self.assertContains(page, 'id="live-text"')
        self.assertContains(page, f'hx-post="{self.edit}"')
        self.assertContains(page, "data-view-form")
        self.assertTrue(Editing.objects.filter(item=self.message).exists())
        plain = self.client.get(self.edit)
        self.assertNotContains(plain, f'hx-post="{self.edit}"')
        self.assertContains(plain, 'id="live-text"')

    def test_a_client_edits_their_own(self):
        mine = ops.create_message(
            project=self.project,
            title="Mine",
            content="Hi",
            creator=self.cleo,
            visible=True,
        )
        self.client.force_login(self.cleo)
        self.assertContains(self.client.get(mine.get_absolute_url()), "data-edit-url")
        edit = reverse("message_edit", args=[mine.pk])
        self.assertContains(self.client.get(edit, headers=HTMX), "hx-post")

    def test_internal_messages_are_404_for_clients(self):
        secret = ops.create_message(
            project=self.project, title="Secret", content="x", creator=self.ada
        )
        self.client.force_login(self.cleo)
        for name in ["message", "message_edit"]:
            url = reverse(name, args=[secret.pk])
            self.assertEqual(self.client.get(url, headers=HTMX).status_code, 404)

    def test_saving_redirects_to_the_page(self):
        response = self.client.post(
            self.edit, {"title": "News", "content": "Changed", "category": ""}
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(Editing.objects.filter(item=self.message).exists())


class FileViewTest(ViewModeBase):
    def setUp(self):
        super().setUp()
        self.file = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="plan.txt"),
            creator=self.ada,
            visible=True,
        )
        self.url = self.file.get_absolute_url()
        self.edit = reverse("file_edit", args=[self.file.pk])

    def test_clickable_with_or_without_a_description(self):
        page = self.client.get(self.url)
        self.assertContains(page, f'data-edit-url="{self.edit}"')
        self.assertContains(page, "Add a description…")
        self.client.force_login(self.cleo)
        page = self.client.get(self.url)
        self.assertNotContains(page, "data-edit-url")
        self.assertNotContains(page, "Add a description")

    def test_the_form_in_place(self):
        page = self.client.get(self.edit, headers=HTMX)
        self.assertContains(page, 'id="live-text"')
        self.assertContains(page, f'hx-post="{self.edit}"')
        self.assertContains(page, 'name="description"')
        self.assertTrue(Editing.objects.filter(item=self.file).exists())

    def test_internal_files_are_404_for_clients(self):
        secret = ops.create_upload(
            project=self.project,
            file=ContentFile(b"y", name="budget.txt"),
            creator=self.ada,
        )
        self.client.force_login(self.cleo)
        for name in ["file", "file_edit"]:
            url = reverse(name, args=[secret.pk])
            self.assertEqual(self.client.get(url, headers=HTMX).status_code, 404)


class AnswerViewTest(ViewModeBase):
    def setUp(self):
        super().setUp()
        self.bob2 = person("Bea")
        project_ops.add_member(self.project, self.bob2, actor=self.ada)
        items = check_in_answers(self.project, [self.ada, self.bob2])
        self.question = items[0].parent
        self.answer = Answer.objects.get(item=items[0])
        self.theirs = Answer.objects.get(item=items[1])
        self.url = self.question.get_absolute_url()
        self.edit = reverse("question_answer", args=[self.question.pk])

    def test_only_their_own_answer_is_clickable(self):
        page = self.client.get(self.url)
        self.assertContains(page, f'id="answer-{self.answer.pk}-text"')
        self.assertContains(page, f'data-edit-region="answer-{self.answer.pk}-text"')
        self.assertNotContains(page, f'data-edit-region="answer-{self.theirs.pk}-text"')
        self.assertNotContains(page, "data-view-form")

    def test_the_form_in_place(self):
        page = self.client.get(self.edit, headers=HTMX)
        region = f"answer-{self.answer.pk}-text"
        self.assertContains(page, f'id="{region}"')
        self.assertContains(page, f'hx-select="#{region}"')
        self.assertNotContains(page, "hx-select-oob")
        self.assertTrue(Editing.objects.filter(item=self.answer.item).exists())
        # The cancel link goes to the question's page
        self.assertContains(page, f'hx-get="{self.url}"')

    def test_clients_dont_see_internal_questions(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.edit, headers=HTMX).status_code, 404)

    def test_clients_see_answers_of_visible_questions_without_edit(self):
        ops.set_visibility(self.question, visible=True, actor=self.ada)
        self.client.force_login(self.cleo)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "data-edit-region")


class EditingMarkerTest(ViewModeBase):
    def test_a_form_in_place_blocks_ticks_until_it_goes(self):
        self.client.force_login(self.bob)
        project_ops.add_member(self.project, self.bob, actor=self.ada)
        self.client.get(self.edit, headers=HTMX)
        self.assertTrue(self.marker(self.bob))
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("item_tick", args=[self.todo.pk]),
            {"index": 0, "checked": 1, "version": self.version()},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Bob is editing this", response.json()["message"])
        self.client.force_login(self.bob)
        self.client.post(reverse("item_editing", args=[self.todo.pk]), {"release": 1})
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("item_tick", args=[self.todo.pk]),
            {"index": 0, "checked": 1, "version": self.version()},
        )
        self.assertEqual(response.status_code, 200)
