"""The mark where people are shown (specs/people.md, "Where"): comments,
messages, the feed and the lantern, assignees, subscribers, members,
check-in answers, the ``@`` list; not in mails"""

import json

from django.test import TestCase
from django.urls import reverse

from biwak.accounts import operations
from biwak.accounts.test_images import picture
from biwak.activity import operations as activity_ops
from biwak.items import operations as item_ops
from biwak.test_utils import check_in_answers, organization, partner, person, project


class PlacesTest(TestCase):
    def setUp(self):
        organization("Example Team", is_own=True)
        self.ada = person("Ada")
        self.ben = person("Ben")
        self.cleo = person("Cleo", client=True)
        self.pia = partner("Pia")
        self.camp = project("Camp", members=[self.ada, self.cleo, self.pia])
        operations.set_image(self.ada, picture(), actor=self.ada)
        self.image = self.ada.image_url
        self.todolist = item_ops.create_list(
            project=self.camp, title="Tasks", creator=self.ada, visible=True
        )
        self.todo = item_ops.create_todo(
            todolist=self.todolist,
            title="Pack",
            creator=self.ada,
            assignees=[self.ada, self.cleo],
        )
        item_ops.add_comment(self.todo, author=self.ada, content="Hello")
        item_ops.add_comment(self.todo, author=self.cleo, content="Hi")
        self.message = item_ops.create_message(
            project=self.camp, title="News", creator=self.ada, visible=True
        )

    def assertMark(self, response, person, *, image):
        html = response.content.decode()
        self.assertEqual(self.image in html, image, f"{person}'s image")
        self.assertIn(f'title="{person}"', html)

    def get(self, viewer, url):
        self.client.force_login(viewer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response

    def test_a_to_do_page_has_it_on_comments_assignees_and_subscribers(self):
        response = self.get(self.ben, self.todo.get_absolute_url())
        html = response.content.decode()
        # Comments: Ada's image, Cleo's initials
        self.assertContains(response, f'src="{self.image}"')
        self.assertIn(
            f'data-avatar-color="{self.cleo.avatar_color}" title="Cleo Example"', html
        )
        # Assignees: pills with the mark
        self.assertRegex(
            html,
            r'class="badge wb-person"[^>]*>(<a [^>]*>)?\s*<(img|span) class="wb-avatar',
        )
        self.assertContains(response, "Subscribers")
        self.assertGreater(html.count("wb-avatar"), 6)

    def test_the_me_menu_has_the_own_mark_and_the_name(self):
        """With an image or the initials; the name is the menu's first
        line, and next to the mark except on phones"""
        for viewer, image in [(self.ada, True), (self.ben, False)]:
            with self.subTest(viewer=viewer):
                html = self.get(viewer, reverse("projects")).content.decode()
                summary = html.split('class="btn btn-sm btn-quiet wb-me-button"')[1]
                summary = summary.split("</summary>")[0]
                self.assertEqual("<img" in summary, image)
                self.assertIn(f'title="{viewer}"', summary)
                self.assertIn(viewer.initials if not image else "wb-avatar", summary)
                self.assertIn(
                    f'<span class="d-none d-sm-inline">{viewer.get_short_name()}</span>',
                    summary,
                )
                self.assertIn(
                    f'<span class="dropdown-item-text fw-semibold">{viewer}</span>',
                    html,
                )

    def test_names_link_to_the_persons_page_for_those_who_may_know_them(self):
        """Subscribers, assignee pills, members and mentions: a link for
        whoever may open the page, plain text for the others"""
        from biwak.activity import mentions
        from biwak.activity.operations import subscribe

        stranger = person("Dora", client=True, organization="Other")
        subscribe(self.ada, self.todo)
        subscribe(stranger, self.todo)
        item_ops.add_comment(
            self.todo, author=self.ada, content=mentions.syntax(self.ada)
        )
        ada_page = reverse("person", args=[self.ada.pk])
        dora = reverse("person", args=[stranger.pk])
        for viewer in (self.ben, self.cleo):
            with self.subTest(viewer=viewer):
                html = self.get(viewer, self.todo.get_absolute_url()).content.decode()
                self.assertIn(f'<a href="{ada_page}" class="wb-person-link">', html)
                self.assertIn(
                    f'<a class="wb-mention wb-person-link" href="{ada_page}"', html
                )
                # Own staff know everybody, Cleo doesn't know Dora: no link
                self.assertEqual(dora in html, viewer == self.ben)
        members = self.get(self.cleo, reverse("project_people", args=[self.camp.pk]))
        self.assertContains(members, f'href="{ada_page}"')
        detail = self.get(self.ada, self.camp.get_absolute_url())
        self.assertContains(detail, f'href="{reverse("person", args=[self.cleo.pk])}"')

    def test_for_a_client_too_with_the_images_of_those_they_may_know(self):
        response = self.get(self.cleo, self.todo.get_absolute_url())
        self.assertContains(response, f'src="{self.image}"')
        image = self.client.get(self.image)
        self.assertEqual(image.status_code, 200)

    def test_a_viewer_who_may_not_know_the_person_gets_the_initials(self):
        stranger = person("Dora", client=True, organization="Other")
        item_ops.add_comment(self.todo, author=stranger, content="Hm")
        operations.set_image(stranger, picture(), actor=stranger)
        # Ada (own staff) may know everybody, Cleo doesn't know Dora
        self.assertContains(
            self.get(self.ada, self.todo.get_absolute_url()), stranger.image_url
        )
        self.client.force_login(self.cleo)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertNotContains(response, stranger.image_url)
        self.assertContains(response, f'title="{stranger}"')

    def test_messages(self):
        response = self.get(self.ben, self.message.get_absolute_url())
        self.assertContains(response, f'src="{self.image}"')
        response = self.get(self.ben, reverse("project_messages", args=[self.camp.pk]))
        self.assertContains(response, f'src="{self.image}"')

    def test_the_feed_and_the_project_page(self):
        for url in [reverse("feed"), reverse("project_feed", args=[self.camp.pk])]:
            self.assertContains(self.get(self.ben, url), f'src="{self.image}"')
        # Members
        response = self.get(self.ben, reverse("project", args=[self.camp.pk]))
        self.assertContains(response, f'src="{self.image}"')
        response = self.get(self.ben, reverse("project_people", args=[self.camp.pk]))
        self.assertContains(response, f'src="{self.image}"')

    def test_the_lantern(self):
        activity_ops.subscribe(self.cleo, self.todo)
        with self.captureOnCommitCallbacks(execute=True):
            item_ops.add_comment(self.todo, author=self.ada, content="Again")
        response = self.get(self.cleo, reverse("lantern"))
        self.assertContains(response, f'src="{self.image}"')

    def test_check_in_answers(self):
        answers = check_in_answers(self.camp, [self.ada, self.ben])
        response = self.get(self.ben, answers[0].get_absolute_url())
        self.assertContains(response, f'src="{self.image}"')

    def test_the_mention_list_carries_what_the_script_needs(self):
        self.client.force_login(self.ben)
        data = json.loads(
            self.client.get(reverse("mentionable", args=[self.todo.pk])).content
        )
        ada = next(p for p in data if p["id"] == self.ada.pk)
        self.assertEqual(
            ada["avatar"],
            {
                "name": "Ada Example",
                "initials": "AE",
                "color": self.ada.avatar_color,
                "image_url": self.image,
            },
        )
        ben = next(p for p in data if p["id"] == self.ben.pk)
        self.assertIsNone(ben["avatar"]["image_url"])

    def test_the_assignee_options_carry_it_too(self):
        response = self.get(self.ben, self.todolist.get_absolute_url())
        self.assertContains(
            response, 'data-avatar="{&quot;name&quot;: &quot;Ada Example&quot;'
        )
        self.assertContains(response, self.image)

    def test_no_images_in_mails(self):
        """Mails need public URLs for images (specs/people.md): none in them"""
        from django.conf import settings

        templates = list((settings.BASE_DIR / "biwak").rglob("templates/**/mails/*"))
        self.assertTrue(templates)
        for path in templates:
            self.assertNotIn("avatar", path.read_text(), path.name)
