import datetime as dt
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from biwak.accounts.models import NotificationLevel
from biwak.activity.models import Action, Event, Notification
from biwak.files import board, operations, queries
from biwak.items import operations as ops
from biwak.items.models import Item, MessageCategory
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.news = MessageCategory.objects.create(name="News", emoji="📣")
        self.shared = self.post("Shared news", visible=True, category=self.news)
        self.secret = self.post("Secret plans", content="Internal **only**")

    def post(self, title, *, creator=None, visible=False, content="", **kwargs):
        return ops.create_message(
            project=self.project,
            title=title,
            content=content,
            creator=creator or self.ada,
            visible=visible,
            **kwargs,
        )

    def titles(self, response, key="rows"):
        return [item.title for item in response.context[key]]


class BoardTest(Fixture, TestCase):
    def url(self):
        return reverse("project_messages", args=[self.project.pk])

    def test_messages_arent_shown_as_alerts(self):
        """The board's rows aren't Django's messages (``messages`` in the
        context is the messages framework's, which base.html shows)"""
        self.post("Suppensud")
        self.client.force_login(self.ada)
        response = self.client.get(self.url())
        self.assertNotContains(response, 'class="alert')

    def test_a_bad_cursor_is_a_bad_request(self):
        self.client.force_login(self.ada)
        for before in ["x", "!!!", "MTIz"]:
            with self.subTest(before=before):
                response = self.client.get(self.url(), {"before": before})
                self.assertEqual(response.status_code, 400)

    def test_staff_sees_everything_with_clients_badge(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url())
        self.assertEqual(self.titles(response), ["Secret plans", "Shared news"])
        self.assertContains(response, "wb-client-badge", count=1)  # the badge, once
        self.assertContains(response, "📣 News")
        self.assertContains(response, "Internal only")  # the excerpt

    def test_client_sees_only_visible_messages(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.url())
        self.assertEqual(self.titles(response), ["Shared news"])
        self.assertNotContains(response, "Secret plans")
        self.assertNotContains(response, "Internal")
        self.assertNotContains(response, "Pin")

    def test_non_members_get_404(self):
        outsider = person("Dan", client=True)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        limited = project("Limited", members=[self.ada], all_access=False)
        self.client.force_login(self.bob)
        url = reverse("project_messages", args=[limited.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_the_trash_is_left_out(self):
        ops.trash(self.shared, actor=self.ada)
        self.client.force_login(self.ada)
        self.assertEqual(self.titles(self.client.get(self.url())), ["Secret plans"])

    def test_comment_counts(self):
        ops.add_comment(self.shared, author=self.bob, content="One")
        ops.add_comment(self.shared, author=self.cleo, content="Two")
        self.client.force_login(self.ada)
        response = self.client.get(self.url())
        counts = {i.title: i.comment_count for i in response.context["rows"]}
        self.assertEqual(counts, {"Shared news": 2, "Secret plans": 0})
        self.assertContains(response, "2 comments")

    def test_order_pinned_first_then_newest_first(self):
        old = self.post("Old", visible=True)
        self.post("New", visible=True)
        Item.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - dt.timedelta(days=3)
        )
        ops.refresh_message_activity(old)
        first = self.post("Pinned first", visible=True)
        second = self.post("Pinned second", visible=True)
        operations.pin_message(first, actor=self.ada)
        operations.pin_message(second, actor=self.ada)
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            response = self.client.get(self.url())
            self.assertEqual(
                self.titles(response, "pinned"), ["Pinned second", "Pinned first"]
            )
            titles = self.titles(response)
            self.assertEqual(titles[0], "New")
            self.assertEqual(titles[-1], "Old")

    def test_a_client_sees_pins_of_visible_messages_only(self):
        operations.pin_message(self.secret, actor=self.ada)
        operations.pin_message(self.shared, actor=self.ada)
        self.client.force_login(self.cleo)
        response = self.client.get(self.url())
        self.assertEqual(self.titles(response, "pinned"), ["Shared news"])

    def test_paging(self):
        for number in range(board.PAGE_SIZE + 3):
            self.post(f"Message {number}", visible=True)
        pinned = self.post("Pinned", visible=True)
        operations.pin_message(pinned, actor=self.ada)
        self.client.force_login(self.cleo)
        response = self.client.get(self.url())
        self.assertEqual(len(response.context["rows"]), board.PAGE_SIZE)
        self.assertEqual(self.titles(response, "pinned"), ["Pinned"])
        cursor = response.context["cursor"]
        self.assertTrue(cursor)
        rest = self.client.get(self.url(), {"before": cursor})
        # Pinned messages only on the first page; everything else once
        self.assertEqual(rest.context["pinned"], [])
        first = set(self.titles(response))
        second = set(self.titles(rest))
        self.assertFalse(first & second)
        self.assertEqual(len(first | second), board.PAGE_SIZE + 4)
        self.assertIsNone(rest.context["cursor"])
        self.assertEqual(self.client.get(self.url(), {"before": "x"}).status_code, 400)


class MessageNewTest(Fixture, TestCase):
    def url(self):
        return reverse("message_new", args=[self.project.pk])

    def test_who_is_told_and_also_tell(self):
        """A line saying who is told by default, "Also tell…" with the
        others who see it, nothing preselected, not the poster (decided
        2026-11-21: additive)"""
        dan = person("Dan")
        Membership.objects.create(project=self.project, user=dan)
        dan.notification_level = NotificationLevel.CONCERNS_ME
        dan.save()
        self.client.force_login(self.ada)
        response = self.client.get(self.url())
        # An internal message (the switch starts off): not Cleo
        self.assertContains(response, "Bob will be told.")
        self.assertContains(response, "Also tell…")
        self.assertContains(response, "data-people-picker")
        self.assertNotContains(response, "data-shown-when")
        self.assertNotContains(response, 'name="notify"')
        form = response.context["form"]
        self.assertEqual(form["also"].value(), None)
        self.assertEqual(set(form.fields["also"].queryset), {dan})
        response = self.post_form(self.ada, also=[dan.pk])
        item = Item.objects.get(title="Hello")
        self.assertEqual(
            set(item.subscriptions.values_list("user", flat=True)),
            {self.ada.pk, self.bob.pk, dan.pk},
        )

    def test_visible_to_clients_lists_and_offers_clients(self):
        """At the top the line follows "Visible to clients" (decided
        2026-11-22): ticked, the clients who'll be told and "Also tell…"
        the project's clients too, told exactly so; unticked, no client is
        listed, offered or told"""
        eve = person("Eve", client=True)
        Membership.objects.create(project=self.project, user=eve)
        eve.notification_level = NotificationLevel.CONCERNS_ME
        eve.save()
        self.client.force_login(self.ada)
        response = self.client.get(self.url())
        form = response.context["form"]
        self.assertEqual(form.fields["also"].intro_lines, (
            "Bob will be told.",
            "Bob and Cleo will be told.",
        ))  # fmt: skip
        self.assertContains(response, '<span data-told="internal">Bob will be told.')
        self.assertContains(
            response, '<span data-told="visible" hidden>Bob and Cleo will be told.'
        )
        self.assertEqual(set(form.fields["also"].queryset), {eve})
        self.assertContains(response, 'data-client="true"')
        self.assertContains(response, 'data-clients-follow="#id_visible"')
        # Internal: no client, also not one picked by hand
        response = self.post_form(self.ada, also=[eve.pk])
        self.assertContains(response, "Clients can&#x27;t see it")
        self.assertFalse(Item.objects.filter(title="Hello").exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.post_form(self.ada, title="Internal")
        item = Item.objects.get(title="Internal")
        self.assertEqual(
            set(item.subscriptions.values_list("user", flat=True)),
            {self.ada.pk, self.bob.pk},
        )
        self.assertFalse(
            Notification.objects.filter(event__item=item, user__is_client=True)
        )
        # Visible: Cleo by default, Eve added
        with self.captureOnCommitCallbacks(execute=True):
            self.post_form(self.ada, visible="on", also=[eve.pk])
        item = Item.objects.get(title="Hello")
        self.assertEqual(
            set(Notification.objects.filter(event__item=item).values_list(
                "user", flat=True
            )),
            {self.bob.pk, self.cleo.pk, eve.pk},
        )  # fmt: skip
        # Shown again ticked: the visible line
        response = self.post_form(self.ada, title="", visible="on")
        self.assertContains(response, '<span data-told="internal" hidden>')
        self.assertContains(
            response, '<span data-told="visible">Bob and Cleo will be told.'
        )

    def test_who_is_told_of_a_clients_message(self):
        """What clients post is visible: everybody on "everything" but them"""
        self.client.force_login(self.cleo)
        response = self.client.get(self.url())
        self.assertContains(response, "Ada and Bob will be told.")
        self.assertEqual(set(response.context["form"].fields["also"].queryset), set())

    def post_form(self, user, **data):
        self.client.force_login(user)
        data = {"title": "Hello", "content": "Text"} | data
        return self.client.post(self.url(), data)

    def test_staff_posts_an_internal_message_by_default(self):
        response = self.post_form(self.ada)
        item = Item.objects.get(title="Hello")
        self.assertRedirects(response, reverse("message", args=[item.pk]))
        self.assertFalse(item.is_client_visible)
        self.assertEqual(item.creator, self.ada)

    def test_staff_chooses_visibility_and_category(self):
        self.post_form(self.ada, visible="on", category=self.news.pk)
        item = Item.objects.get(title="Hello")
        self.assertTrue(item.is_client_visible)
        self.assertEqual(item.message.category, self.news)

    def test_who_is_told(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post_form(self.ada, visible="on")
        item = Item.objects.get(title="Hello")
        self.assertEqual(
            {n.user for n in Event.objects.get(item=item).notifications.all()},
            {self.bob, self.cleo},
        )

    def test_nobody_and_only_these_people_are_gone(self):
        """What older pages post can't hide a message from those who want
        to hear (decided 2026-11-21: additive)"""
        with self.captureOnCommitCallbacks(execute=True):
            self.post_form(self.ada, visible="on", notify="nobody", people=[])
        item = Item.objects.get(title="Hello")
        self.assertEqual(
            {n.user for n in Event.objects.get(item=item).notifications.all()},
            {self.bob, self.cleo},
        )

    def test_a_client_posts_visible_messages(self):
        response = self.post_form(self.cleo, visible="on")
        item = Item.objects.get(title="Hello")
        self.assertTrue(item.is_client_visible)
        self.assertRedirects(response, reverse("message", args=[item.pk]))

    def test_the_form_has_no_switch_for_clients(self):
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get(self.url()), "Visible to clients")
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(self.url()), "Visible to clients")

    def test_404_without_access(self):
        self.client.force_login(person("Dan", client=True))
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url(), {"title": "x"}).status_code, 404)


class MessageTest(Fixture, TestCase):
    def url(self, item, name="message"):
        return reverse(name, args=[item.pk])

    def test_staff_reads_both(self):
        self.client.force_login(self.ada)
        for item in [self.shared, self.secret]:
            self.assertEqual(self.client.get(self.url(item)).status_code, 200)

    def test_the_banner_and_badge_on_visible_messages(self):
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(self.url(self.shared)), "Clients can see this"
        )
        self.assertNotContains(
            self.client.get(self.url(self.secret)), "Clients can see this"
        )

    def test_a_client_gets_404_for_internal_messages(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url(self.shared)).status_code, 200)
        for name in ["message", "message_edit"]:
            self.assertEqual(
                self.client.get(self.url(self.secret, name)).status_code, 404
            )
        for name in ["message", "message_pin"]:
            self.assertEqual(
                self.client.post(self.url(self.secret, name)).status_code, 404
            )
        self.assertEqual(
            self.client.post(
                self.url(self.secret), {"form": "comment", "content": "Hi"}
            ).status_code,
            404,
        )
        self.assertFalse(self.secret.comments.exists())

    def test_comments(self):
        self.client.force_login(self.cleo)
        response = self.client.post(
            self.url(self.shared), {"form": "comment", "content": "Thanks"}
        )
        self.assertRedirects(
            response, self.url(self.shared) + "#comments", fetch_redirect_response=False
        )
        self.assertContains(self.client.get(self.url(self.shared)), "Thanks")

    def test_the_message_is_rendered_as_markdown(self):
        item = self.post("MD", visible=True, content="Some **bold** text")
        self.client.force_login(self.cleo)
        self.assertContains(self.client.get(self.url(item)), "<strong>bold</strong>")

    def test_editing(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url(self.secret, "message_edit"),
            {"title": "New title", "content": "New", "category": self.news.pk},
        )
        self.assertRedirects(response, self.url(self.secret))
        self.secret.refresh_from_db()
        self.assertEqual(self.secret.title, "New title")
        self.assertEqual(self.secret.message.category, self.news)

    def test_clients_edit_only_their_own_messages(self):
        mine = self.post("Mine", creator=self.cleo, visible=True)
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.get(self.url(mine, "message_edit")).status_code, 200
        )
        self.assertEqual(
            self.client.get(self.url(self.shared, "message_edit")).status_code, 403
        )
        self.assertNotContains(
            self.client.get(self.url(self.shared)),
            self.url(self.shared, "message_edit"),
        )

    def test_the_switch_is_for_staff(self):
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(self.url(self.secret)), "Show to clients")
        self.client.post(reverse("switch", args=[self.secret.pk]), {"visible": "1"})
        self.secret.refresh_from_db()
        self.assertTrue(self.secret.is_client_visible)
        self.client.force_login(self.cleo)
        self.assertNotContains(
            self.client.get(self.url(self.shared)), "Hide from clients"
        )
        response = self.client.post(reverse("switch", args=[self.shared.pk]))
        self.assertEqual(response.status_code, 403)

    def test_trashing(self):
        self.client.force_login(self.ada)
        self.client.post(reverse("item_trash", args=[self.secret.pk]))
        self.assertEqual(self.client.get(self.url(self.secret)).status_code, 404)

    def test_mentionable_list_works_for_messages(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("mentionable", args=[self.secret.pk]))
        self.assertEqual(response.status_code, 200)
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("mentionable", args=[self.secret.pk]))
        self.assertEqual(response.status_code, 404)


class PinningTest(Fixture, TestCase):
    def pin_url(self, item):
        return reverse("message_pin", args=[item.pk])

    def test_staff_pins_and_unpins(self):
        self.client.force_login(self.ada)
        response = self.client.post(self.pin_url(self.shared))
        self.assertRedirects(response, self.shared.get_absolute_url())
        self.assertIsNotNone(Item.objects.get(pk=self.shared.pk).message.pinned_at)
        self.assertContains(self.client.get(self.shared.get_absolute_url()), "Unpin")
        self.client.post(self.pin_url(self.shared), {"unpin": "1"})
        self.assertIsNone(Item.objects.get(pk=self.shared.pk).message.pinned_at)
        self.assertContains(self.client.get(self.shared.get_absolute_url()), "Pin")

    def test_from_the_board_back_to_the_board(self):
        board_url = reverse("project_messages", args=[self.project.pk])
        self.client.force_login(self.ada)
        response = self.client.post(self.pin_url(self.shared), {"next": board_url})
        self.assertRedirects(response, board_url)
        self.assertContains(self.client.get(board_url), "Unpin")

    def test_a_client_cannot_pin(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.post(self.pin_url(self.shared)).status_code, 403)
        self.assertIsNone(Item.objects.get(pk=self.shared.pk).message.pinned_at)
        # Neither the buttons
        self.assertNotContains(
            self.client.get(self.shared.get_absolute_url()), self.pin_url(self.shared)
        )
        board_url = reverse("project_messages", args=[self.project.pk])
        self.assertNotContains(self.client.get(board_url), self.pin_url(self.shared))
        # Also not what they posted themselves
        mine = ops.create_message(
            project=self.project, title="Mine", creator=self.cleo, visible=True
        )
        self.assertEqual(self.client.post(self.pin_url(mine)).status_code, 403)

    def test_events_are_in_the_feed_for_those_who_see_the_message(self):
        operations.pin_message(self.shared, actor=self.ada)
        operations.pin_message(self.secret, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_feed", args=[self.project.pk]))
        self.assertContains(response, "pinned")
        self.assertContains(response, "Secret plans")
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("project_feed", args=[self.project.pk]))
        self.assertContains(response, "Shared news")
        self.assertNotContains(response, "Secret plans")
        self.assertTrue(Event.objects.filter(action=Action.PINNED).count(), 2)


# The rules with small numbers; the numbers themselves: test_five_and_a_link
@patch.object(queries, "FRONT_MESSAGES", 3)
class ProjectPageTest(Fixture, TestCase):
    def url(self):
        return reverse("project", args=[self.project.pk])

    def titles_on_page(self, user):
        self.client.force_login(user)
        response = self.client.get(self.url())
        return [i.title for i in response.context["front_messages"]], response

    def test_three_messages_newest_first(self):
        for n in range(3):
            self.post(f"Visible {n}", visible=True)
        titles, response = self.titles_on_page(self.ada)
        self.assertEqual(titles, ["Visible 2", "Visible 1", "Visible 0"][:3])
        self.assertContains(response, 'href="/messages/')

    def test_pinned_first_and_any_number_of_them(self):
        for n in range(3):
            self.post(f"Visible {n}", visible=True)
        pins = [self.shared, self.secret]
        for message in pins:
            operations.pin_message(message, actor=self.ada)
        titles, _response = self.titles_on_page(self.ada)
        self.assertEqual(titles, ["Secret plans", "Shared news", "Visible 2"])
        extra = [self.post(f"Pin {n}", visible=True) for n in range(3)]
        for message in extra:
            operations.pin_message(message, actor=self.ada)
        titles, _response = self.titles_on_page(self.ada)
        self.assertEqual(len(titles), 5)  # more pinned than three: only those
        self.assertEqual(titles[0], "Pin 2")

    def test_a_client_gets_only_visible_ones(self):
        operations.pin_message(self.secret, actor=self.ada)
        titles, response = self.titles_on_page(self.cleo)
        self.assertEqual(titles, ["Shared news"])
        self.assertNotContains(response, "Secret plans")

    def test_docs_and_files_counts(self):
        ops.create_folder(project=self.project, title="Specs", creator=self.ada)
        ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, visible=True
        )
        self.assertEqual(
            queries.root_counts(self.project, self.ada),
            {"folders": 1, "docs": 1, "files": 0},
        )
        self.assertEqual(
            queries.root_counts(self.project, self.cleo),
            {"folders": 0, "docs": 1, "files": 0},
        )


@patch.object(queries, "FRONT_FILES", 3)
class FrontFilesTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.old = ops.create_doc(
            project=self.project, title="Old doc", creator=self.ada, visible=True
        )
        self.folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada, visible=True
        )
        self.nested = ops.create_doc(
            project=self.project,
            title="Nested doc",
            creator=self.bob,
            visible=True,
            parent=self.folder,
        )
        self.upload = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("plan.txt", b"Plan"),
            creator=self.ada,
            visible=True,
        )
        self.internal = ops.create_doc(
            project=self.project, title="Internal doc", creator=self.ada
        )

    def page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("project", args=[self.project.pk]))

    def test_staff_sees_the_latest_three_changed(self):
        response = self.page(self.ada)
        self.assertEqual(
            [i.title for i in response.context["front_files"]],
            ["Internal doc", "plan.txt", "Nested doc"],
        )
        self.assertContains(response, "Internal doc")
        self.assertContains(response, reverse("project_files", args=[self.project.pk]))

    def test_changing_a_doc_brings_it_up(self):
        Item.objects.filter(pk=self.old.pk).update(
            updated_at=timezone.now() + dt.timedelta(minutes=1)
        )
        titles = [i.title for i in self.page(self.ada).context["front_files"]]
        self.assertEqual(titles[0], "Old doc")

    def test_a_client_sees_visible_ones_only(self):
        response = self.page(self.cleo)
        self.assertEqual(
            [i.title for i in response.context["front_files"]],
            ["plan.txt", "Nested doc", "Old doc"],
        )
        self.assertNotContains(response, "Internal doc")
        self.assertContains(response, "plan.txt")

    def test_a_fixed_number_of_queries(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.page(self.ada)
            return len(queries)

        Event.objects.all().delete()  # the feed beside has its own queries
        count()
        before = count()
        for n in range(3):
            ops.create_doc(
                project=self.project, title=f"More {n}", creator=self.ada, visible=True
            )
        Event.objects.all().delete()
        self.assertEqual(count(), before)

    def test_empty(self):
        Item.objects.filter(kind__in=["doc", "file"]).delete()
        self.assertContains(self.page(self.ada), "No docs or files yet.")


class FrontNumbersTest(Fixture, TestCase):
    def test_five_and_a_link(self):
        """Five messages and five docs and files on the project page, and a
        link to all messages (decided 2026-11-21)"""
        self.assertEqual((queries.FRONT_MESSAGES, queries.FRONT_FILES), (5, 5))
        for n in range(6):
            self.post(f"Visible {n}", visible=True)
        self.client.force_login(self.ada)
        response = self.client.get(self.project.get_absolute_url())
        self.assertEqual(len(response.context["front_messages"]), 5)
        self.assertContains(response, "All messages")


class OrderTest(Fixture, TestCase):
    """The board's order (specs/files.md, "The message board", decided
    2026-11-22): "Latest update" by default, or "Newest posts"; pinned
    messages on top either way"""

    def setUp(self):
        super().setUp()
        self.old = self.post("Old but discussed", visible=True)
        self.recent = self.post("Recent", visible=True)
        self.ago(self.old, days=3)
        self.ago(self.recent, days=1)
        self.ago(self.shared, days=2)
        self.ago(self.secret, days=4)
        # Newest posts: Recent, Shared news, Old but discussed, Secret plans
        ops.add_comment(self.old, author=self.cleo, content="What about this?")

    def ago(self, item, **delta):
        """Posted earlier, comments and all"""
        Item.objects.filter(pk=item.pk).update(
            created_at=timezone.now() - dt.timedelta(**delta)
        )
        ops.refresh_message_activity(item)

    def url(self):
        return reverse("project_messages", args=[self.project.pk])

    def activity(self, item):
        item.message.refresh_from_db()
        return item.message.last_activity_at

    def test_posting_and_commenting_count_editing_doesnt(self):
        item = self.post("Fresh")
        self.assertEqual(self.activity(item), item.created_at)
        comment = ops.add_comment(item, author=self.bob, content="Yes")
        self.assertEqual(self.activity(item), comment.created_at)
        operations.update_message(item, actor=self.ada, title="Changed", content="x")
        self.assertEqual(self.activity(item), comment.created_at)

    def test_the_activity_is_the_later_of_posting_and_comments(self):
        """Also for times set afterwards (the importer's)"""
        comment = self.old.comments.get()
        self.assertEqual(self.activity(self.old), comment.created_at)
        self.ago(self.recent, days=1)
        self.assertEqual(
            self.activity(self.recent),
            Item.objects.get(pk=self.recent.pk).created_at,
        )

    def test_staff_sets_the_order_clients_cant(self):
        self.assertEqual(self.project.messages_order, "latest")
        operations.set_messages_order(self.project, "newest", actor=self.ada)
        self.project.refresh_from_db()
        self.assertEqual(self.project.messages_order, "newest")
        with self.assertRaises(PermissionDenied):
            operations.set_messages_order(self.project, "latest", actor=self.cleo)
        with self.assertRaises(ValueError):
            operations.set_messages_order(self.project, "sideways", actor=self.ada)
        self.assertFalse(Event.objects.filter(action=Action.EDITED).exists())

    def test_the_board_in_both_orders(self):
        latest = ["Old but discussed", "Recent", "Shared news", "Secret plans"]
        newest = ["Recent", "Shared news", "Old but discussed", "Secret plans"]
        for user, hidden in [(self.ada, set()), (self.cleo, {"Secret plans"})]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(self.url())
                expected = [t for t in latest if t not in hidden]
                self.assertEqual(self.titles(response), expected)
                self.assertContains(response, 'aria-label="Order"')
                response = self.client.get(self.url(), {"order": "newest"})
                expected = [t for t in newest if t not in hidden]
                self.assertEqual(self.titles(response), expected)
                # Nonsense is the board's order
                response = self.client.get(self.url(), {"order": "x"})
                self.assertEqual(self.titles(response)[0], "Old but discussed")
        operations.set_messages_order(self.project, "newest", actor=self.ada)
        response = self.client.get(self.url())
        self.assertEqual(
            self.titles(response), ["Recent", "Shared news", "Old but discussed"]
        )
        response = self.client.get(self.url(), {"order": "latest"})
        self.assertEqual(self.titles(response)[0], "Old but discussed")

    def test_pinned_stay_on_top(self):
        operations.pin_message(self.secret, actor=self.ada)
        self.client.force_login(self.ada)
        for order in ["latest", "newest"]:
            response = self.client.get(self.url(), {"order": order})
            self.assertEqual(self.titles(response, "pinned"), ["Secret plans"])
            self.assertNotIn("Secret plans", self.titles(response))

    def test_staff_change_it_on_the_board_clients_look(self):
        url = reverse("project_messages_order", args=[self.project.pk])
        self.client.force_login(self.ada)
        response = self.client.get(self.url())
        self.assertContains(response, f'action="{url}"')
        self.assertContains(
            response, 'name="order"\n          value="newest"', html=False
        )
        response = self.client.post(url, {"order": "newest"})
        self.assertRedirects(response, self.url())
        self.project.refresh_from_db()
        self.assertEqual(self.project.messages_order, "newest")
        self.assertEqual(self.client.post(url, {"order": "x"}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.cleo)
        response = self.client.get(self.url())
        self.assertNotContains(response, url)
        self.assertContains(response, 'href="?order=latest"')
        self.assertEqual(self.client.post(url, {"order": "latest"}).status_code, 403)
        self.project.refresh_from_db()
        self.assertEqual(self.project.messages_order, "newest")

    def test_paging_in_both_orders(self):
        """Each message once across the pages, in order, also when
        comments move old ones up"""
        start = timezone.now() - dt.timedelta(days=30)
        items = []
        for number in range(board.PAGE_SIZE + 3):
            item = self.post(f"Message {number}", visible=True)
            Item.objects.filter(pk=item.pk).update(
                created_at=start + dt.timedelta(hours=number)
            )
            ops.refresh_message_activity(item)
            items.append(item)
        # The oldest gets a comment: first by latest update, last by posting
        ops.add_comment(items[0], author=self.bob, content="Bump")
        self.client.force_login(self.cleo)
        for order in ["latest", "newest"]:
            with self.subTest(order=order):
                response = self.client.get(self.url(), {"order": order})
                seen = self.titles(response)
                self.assertEqual(len(seen), board.PAGE_SIZE)
                cursor = response.context["cursor"]
                if order == "newest":
                    # Not the board's order: the next page stays in it
                    self.assertContains(response, "?order=newest&amp;before=")
                rest = self.client.get(self.url(), {"order": order, "before": cursor})
                self.assertIsNone(rest.context["cursor"])
                seen += self.titles(rest)
                self.assertEqual(len(seen), len(set(seen)))
                self.assertEqual(len(seen), board.PAGE_SIZE + 6)
                if order == "latest":
                    self.assertEqual(seen[0], "Message 0")
                else:
                    self.assertEqual(seen[3], f"Message {board.PAGE_SIZE + 2}")
                    self.assertEqual(seen[-1], "Message 0")

    def test_the_project_page_follows_the_board(self):
        url = self.project.get_absolute_url()
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            response = self.client.get(url)
            titles = [i.title for i in response.context["front_messages"]]
            self.assertEqual(titles[0], "Old but discussed")
        operations.set_messages_order(self.project, "newest", actor=self.ada)
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            response = self.client.get(url)
            titles = [i.title for i in response.context["front_messages"]]
            self.assertEqual(titles[:2], ["Recent", "Shared news"])
            self.assertNotEqual(user.is_client, "Secret plans" in titles)
