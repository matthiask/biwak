"""Ticking while someone edits (specs/editor.md): the editing marker, the
refused ticks and the edit forms refusing stale saves"""

import datetime as dt

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.checkins import operations as checkin_ops
from biwak.items import editing, operations as ops
from biwak.items.models import Editing, Kind
from biwak.richtext import checklists
from biwak.test_utils import bare_doc, check_in_answers, person, project


TEXT = "Packing\n\n- [ ] tent\n- [x] stove\n- [ ] rope\n"


class Fixture(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")  # staff who isn't a member
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Pack", creator=self.ada, notes=TEXT
        )
        self.message = ops.create_message(
            project=self.project,
            title="Camp",
            creator=self.ada,
            content=TEXT,
            visible=True,
        )

    def tick(self, user, item, **data):
        self.client.force_login(user)
        data = {
            "index": 0,
            "version": checklists.text_hash(ops.text_of(item)),
            "checked": "1",
        } | data
        return self.client.post(reverse("item_tick", args=[item.pk]), data)


class MarkerTest(Fixture):
    def test_start_renews_and_stop(self):
        editing.start(self.todo, self.ada)
        editing.start(self.todo, self.ada)
        self.assertEqual(Editing.objects.count(), 1)
        self.assertEqual(editing.holders(self.todo), [self.ada])
        editing.stop(self.todo, self.ada)
        self.assertEqual(editing.holders(self.todo), [])

    def test_expires_two_minutes_after_the_last_renewal(self):
        start = timezone.now()
        editing.start(self.todo, self.ada, now=start)
        for seconds, expected in [(60, [self.ada]), (119, [self.ada]), (121, [])]:
            self.assertEqual(
                editing.holders(self.todo, now=start + dt.timedelta(seconds=seconds)),
                expected,
                seconds,
            )
        editing.start(self.todo, self.ada, now=start + dt.timedelta(seconds=100))
        self.assertEqual(
            editing.holders(self.todo, now=start + dt.timedelta(seconds=200)),
            [self.ada],
        )

    def test_prune_deletes_the_expired(self):
        editing.start(self.todo, self.ada, now=timezone.now() - dt.timedelta(hours=1))
        editing.start(self.message, self.ada)
        self.assertEqual(editing.prune(), 1)
        self.assertEqual(Editing.objects.get().item, self.message)

    def test_the_endpoint_starts_and_releases(self):
        url = reverse("item_editing", args=[self.todo.pk])
        self.client.force_login(self.ada)
        self.assertEqual(self.client.post(url).status_code, 204)
        self.assertEqual(editing.holders(self.todo), [self.ada])
        self.assertEqual(self.client.post(url, {"release": "1"}).status_code, 204)
        self.assertEqual(editing.holders(self.todo), [])
        # Nothing to edit on a list; the hidden are not found
        self.assertEqual(
            self.client.post(
                reverse("item_editing", args=[self.shared.pk])
            ).status_code,
            403,
        )
        internal = ops.create_message(
            project=self.project, title="Internal", creator=self.ada, content="x"
        )
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.post(reverse("item_editing", args=[internal.pk])).status_code,
            404,
        )

    def test_saving_clears_it(self):
        for item, save in [
            (self.todo, lambda: ops.update_todo(self.todo, actor=self.ada, title="x")),
            (
                self.message,
                lambda: __import__(
                    "biwak.files.operations", fromlist=["x"]
                ).update_message(self.message, actor=self.ada, title="x"),
            ),
        ]:
            editing.start(item, self.ada)
            editing.start(item, self.bob)
            save()
            self.assertEqual(editing.holders(item), [self.bob])

    def test_saving_a_file_and_answer_clears_it(self):
        from biwak.files import operations as file_ops

        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            description=TEXT,
        )
        (answer,) = check_in_answers(self.project, [self.ada], content=TEXT)
        for item in [upload, answer]:
            editing.start(item, self.ada)
        file_ops.update_upload(upload, actor=self.ada, description="new")
        checkin_ops.update_answer(answer.answer, "new", actor=self.ada)
        self.assertEqual(Editing.objects.count(), 0)

    def test_saving_a_doc_keeps_it(self):
        # Docs are edited live: the marker is the open editor's
        # (collab.consumers), saving (the API, a tick) doesn't end it
        from biwak.files import operations as file_ops

        doc = ops.create_doc(
            project=self.project, title="Doc", creator=self.ada, content=TEXT
        )
        editing.start(doc, self.ada)
        file_ops.update_doc(doc, actor=self.ada, content="new")
        self.assertEqual(editing.holders(doc), [self.ada])

    def test_the_edit_pages_set_it_and_cancel_clears_it(self):
        self.client.force_login(self.ada)
        for name, item in [("message_edit", self.message)]:
            response = self.client.get(reverse(name, args=[item.pk]))
            self.assertContains(response, "data-editing=")
            self.assertContains(response, "data-editing-release")
            self.assertEqual(editing.holders(item), [self.ada])
            # Cancel
            self.client.post(reverse("item_editing", args=[item.pk]), {"release": "1"})
            self.assertEqual(editing.holders(item), [])

    def test_the_pages_of_the_other_kinds(self):
        self.client.force_login(self.ada)
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
        )
        self.client.get(reverse("file_edit", args=[upload.pk]))
        self.assertEqual(editing.holders(upload), [self.ada])
        (answer,) = check_in_answers(self.project, [self.ada])
        response = self.client.get(reverse("question_answer", args=[answer.parent_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(editing.holders(answer), [self.ada])
        # The to-do page shows the to-do: no form, no marker; the form
        # (its edit URL, or in place of the view) announces itself
        response = self.client.get(self.todo.get_absolute_url())
        self.assertNotContains(response, "data-editing=")
        self.assertEqual(editing.holders(self.todo), [])
        self.client.get(self.todo.get_absolute_url() + "edit/")
        self.assertEqual(editing.holders(self.todo), [self.ada])


class RefusedTickTest(Fixture):
    def test_without_a_form_open_ticks_work(self):
        self.assertEqual(self.tick(self.ada, self.todo).status_code, 200)

    def test_staff_see_the_name(self):
        editing.start(self.todo, self.ada)
        response = self.tick(self.bob, self.todo)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "message": "Ada is editing this; try again when they're done.",
                "reload": False,
            },
        )
        self.todo.todo.refresh_from_db()
        self.assertEqual(self.todo.todo.notes, TEXT)

    def test_clients_see_names_of_the_people_they_may_know(self):
        editing.start(self.todo, self.ada)
        response = self.tick(self.cleo, self.todo)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Ada is editing this", response.json()["message"])

    def test_clients_do_not_learn_the_names_of_other_staff(self):
        editing.start(self.todo, self.bob)
        message = self.tick(self.cleo, self.todo).json()["message"]
        self.assertEqual(
            message, "Someone is editing this; try again when they're done."
        )
        self.assertNotIn("Bob", message)

    def test_several_people(self):
        editing.start(self.todo, self.ada)
        editing.start(self.todo, self.bob)
        message = self.tick(self.cleo, self.todo).json()["message"]
        self.assertTrue(message.startswith("Several people are editing"))

    def test_the_own_form_wins_too(self):
        editing.start(self.todo, self.ada)
        response = self.tick(self.ada, self.todo)
        self.assertEqual(response.status_code, 409)
        self.assertIn("You have the edit form", response.json()["message"])

    def test_every_kind_with_a_form(self):
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            description=TEXT,
        )
        (answer,) = check_in_answers(self.project, [self.ada], content=TEXT)
        for item in [self.message, upload, answer]:
            editing.start(item, self.ada)
            self.assertEqual(self.tick(self.bob, item).status_code, 409)

    def test_docs_never_wait_for_the_live_editor(self):
        # The marker of a doc is the open live editor's (collab.consumers)
        doc = bare_doc(
            project=self.project, title="Doc", creator=self.ada, content=TEXT
        )
        editing.start(doc, self.ada)
        editing.start(doc, self.bob)
        # Somebody else's editor, then one's own, then both
        editing.stop(doc, self.ada)
        response = self.tick(self.ada, doc)
        self.assertEqual(response.status_code, 200)
        editing.start(doc, self.ada)
        editing.stop(doc, self.bob)
        response = self.tick(self.ada, doc, index=2, version=response.json()["version"])
        self.assertEqual(response.status_code, 200)
        editing.start(doc, self.bob)
        response = self.tick(
            self.bob, doc, index=1, checked="0", version=response.json()["version"]
        )
        self.assertEqual(response.status_code, 200)
        doc.doc.refresh_from_db()
        self.assertEqual(
            doc.doc.content, "Packing\n\n- [x] tent\n- [ ] stove\n- [x] rope\n"
        )
        self.assertEqual(len(editing.holders(doc)), 2)

    def test_the_doc_page_tells_who_has_the_editor_open(self):
        doc = ops.create_doc(
            project=self.project, title="Doc", creator=self.ada, content=TEXT
        )
        editing.start(doc, self.ada)
        self.client.force_login(self.bob)
        self.assertContains(
            self.client.get(doc.get_absolute_url()), "Ada is editing this."
        )
        # Not oneself
        self.client.force_login(self.ada)
        self.assertNotContains(
            self.client.get(doc.get_absolute_url()), "is editing this"
        )

    def test_an_expired_marker_does_not_block(self):
        editing.start(self.todo, self.ada, now=timezone.now() - dt.timedelta(minutes=3))
        self.assertEqual(self.tick(self.bob, self.todo).status_code, 200)

    def test_it_works_again_when_the_form_is_saved(self):
        editing.start(self.todo, self.ada)
        self.assertEqual(self.tick(self.bob, self.todo).status_code, 409)
        ops.update_todo(self.todo, actor=self.ada, title="Pack the van")
        self.assertEqual(self.tick(self.bob, self.todo).status_code, 200)

    def test_comments_have_no_form_to_wait_for(self):
        comment = ops.add_comment(self.todo, author=self.ada, content="- [ ] one")
        editing.start(self.todo, self.ada)
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("item_tick", args=[self.todo.pk]),
            {
                "index": 0,
                "version": checklists.text_hash(comment.content),
                "comment": comment.pk,
                "checked": "1",
            },
        )
        self.assertEqual(response.status_code, 200)


class ChangedTextTest(Fixture):
    def test_who_changed_it_last(self):
        ops.update_todo(self.todo, actor=self.bob, notes="- [ ] new one")
        response = self.tick(self.ada, self.todo, version="old")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"message": "Changed by Bob a moment ago.", "reload": True},
        )

    def test_a_while_ago(self):
        ops.update_todo(self.todo, actor=self.bob, notes="- [ ] new one")
        from biwak.activity.models import Event

        Event.objects.filter(item=self.todo, actor=self.bob).update(
            created_at=timezone.now() - dt.timedelta(hours=2, minutes=5)
        )
        message = self.tick(self.ada, self.todo, version="old").json()["message"]
        # One unit, like the ``ago`` filter (decided 2026-11-22)
        self.assertEqual(message, "Changed by Bob 2\xa0hours ago.")

    def test_clients_do_not_learn_who(self):
        ops.update_todo(self.todo, actor=self.bob, notes="- [ ] new one")
        message = self.tick(self.cleo, self.todo, version="old").json()["message"]
        self.assertEqual(message, "Changed by someone a moment ago.")

    def test_comments(self):
        comment = ops.add_comment(self.todo, author=self.cleo, content="- [ ] one")
        self.client.force_login(self.cleo)
        response = self.client.post(
            reverse("item_tick", args=[self.todo.pk]),
            {"index": 0, "version": "old", "comment": comment.pk, "checked": "1"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Changed by you", response.json()["message"])


class StaleSaveTest(Fixture):
    """The edit forms carry the version of the title and text from when they
    opened (``base``); somebody else saving meanwhile refuses the save"""

    def setUp(self):
        super().setUp()
        self.upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            description="First",
        )
        (self.answer,) = check_in_answers(self.project, [self.ada], content="First")

    def post_to(self, item):
        match item.kind:
            case "todo":
                return item.get_absolute_url(), {"form": "todo", "notes": "Mine"}
            case "message":
                return reverse("message_edit", args=[item.pk]), {"content": "Mine"}
            case "file":
                return reverse("file_edit", args=[item.pk]), {"description": "Mine"}
            case "answer":
                return reverse("question_answer", args=[item.parent_id]), {
                    "content": "Mine",
                    "occurrence": item.answer.occurrence_id,
                }

    def change(self, item):
        from biwak.files import operations as file_ops

        match item.kind:
            case "todo":
                ops.update_todo(item, actor=self.bob, notes="Bob's")
            case "message":
                file_ops.update_message(item, actor=self.bob, content="Bob's")
            case "file":
                file_ops.update_upload(item, actor=self.bob, description="Bob's")
            case "answer":
                checkin_ops.update_answer(item.answer, "Bob's", actor=self.bob)

    def text(self, item):
        return ops.text_of(type(item).objects.get(pk=item.pk))

    def open_form(self, user, item):
        """The page of the form, and what its hidden ``base`` field carries"""
        self.client.force_login(user)
        url, _ = self.post_to(item)
        # The to-do's form is the page of its own edit URL
        response = self.client.get(url + "edit/" if item.kind == Kind.TODO else url)
        self.assertContains(response, 'name="base')
        return response

    def test_the_form_carries_the_version_and_refuses_a_stale_save(self):
        for item in [self.todo, self.message, self.upload, self.answer]:
            with self.subTest(item.kind):
                base = editing.version(item)
                response = self.open_form(self.ada, item)
                self.assertContains(response, f'value="{base}"')
                self.change(item)
                url, data = self.post_to(item)
                data = data | {"title": item.title, "base": base}
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 200, item.kind)
                self.assertContains(response, "Bob changed this a moment ago")
                self.assertEqual(self.text(item), "Bob's")

    def test_a_current_form_saves(self):
        for item in [self.todo, self.message, self.upload, self.answer]:
            with self.subTest(item.kind):
                self.open_form(self.ada, item)
                url, data = self.post_to(item)
                data = data | {"title": item.title, "base": editing.version(item)}
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 302, item.kind)
                self.assertEqual(self.text(item), "Mine")

    def test_a_client_is_told_someone(self):
        self.client.force_login(self.cleo)
        base = editing.version(self.message)
        self.change(self.message)
        client_message = ops.create_message(
            project=self.project, title="Cleo's", creator=self.cleo, content="First"
        )
        base = editing.version(client_message)
        from biwak.files import operations as file_ops

        file_ops.update_message(client_message, actor=self.bob, content="Bob's")
        response = self.client.post(
            reverse("message_edit", args=[client_message.pk]),
            {"title": "Cleo's", "content": "Mine", "base": base},
        )
        self.assertContains(response, "Someone changed this")
        self.assertNotContains(response, "Bob")

    def test_no_base_no_check(self):
        # The API and older forms save without
        self.change(self.todo)
        ops.update_todo(self.todo, actor=self.ada, notes="Mine")
        self.assertEqual(self.text(self.todo), "Mine")


class DocHeadsUpTest(Fixture):
    """No locks (specs/collaboration.md): the doc's page only says who is
    editing it"""

    def setUp(self):
        super().setUp()
        self.doc = ops.create_doc(
            project=self.project,
            title="Doc",
            creator=self.ada,
            content=TEXT,
            visible=True,
        )

    def page(self, user):
        self.client.force_login(user)
        return self.client.get(self.doc.get_absolute_url())

    def test_nobody_editing(self):
        self.assertNotContains(self.page(self.bob), "is editing this")

    def test_somebody_else_editing(self):
        editing.start(self.doc, self.ada)
        response = self.page(self.bob)
        self.assertContains(response, "Ada is editing this.")
        # Nobody is kept out
        self.assertContains(response, reverse("doc_edit", args=[self.doc.pk]))
        self.assertEqual(
            self.client.get(reverse("doc_edit", args=[self.doc.pk])).status_code, 200
        )
        # Not oneself
        self.assertNotContains(self.page(self.ada), "is editing this")

    def test_clients_learn_only_names_they_may_know(self):
        editing.start(self.doc, self.ada)
        self.assertContains(self.page(self.cleo), "Ada is editing this.")
        editing.stop(self.doc, self.ada)
        editing.start(self.doc, self.bob)
        response = self.page(self.cleo)
        self.assertContains(response, "Someone is editing this.")
        self.assertNotContains(response, "Bob")

    def test_several_and_expired(self):
        editing.start(self.doc, self.ada)
        editing.start(self.doc, self.cleo)
        self.assertContains(self.page(self.bob), "Several people are editing this.")
        Editing.objects.update(seen_at=timezone.now() - dt.timedelta(minutes=3))
        self.assertNotContains(self.page(self.bob), "is editing this")
