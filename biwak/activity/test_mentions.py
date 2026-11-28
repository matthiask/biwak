import datetime as dt

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import APIToken, User
from biwak.activity import mentions
from biwak.activity.mails import send_mails, unsubscribe_url
from biwak.activity.models import Action, Event, Mention, Subscription
from biwak.activity.operations import subscribe, unsubscribe
from biwak.api_conventions import html
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.templatetags.biwak import excerpt, item_title, markdown
from biwak.test_utils import person, project


class MentionsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.dan = person("Dan", client=True)  # not a member
        self.project = project(members=[self.ada, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )

    def test_mentionable_people_match_visibility(self):
        """The list of people who can see an item is the one check's
        result, person by person"""
        limited = project("Salaries", members=[self.ada], all_access=False)
        salaries = ops.create_list(project=limited, title="2027", creator=self.ada)
        inactive = person("Eve", is_active=False)
        people = [self.ada, self.bob, self.cleo, self.dan, inactive]
        for item in [self.todo, self.secret, salaries]:
            with self.subTest(item=item):
                expected = {
                    user
                    for user in people
                    if Item.objects.visible_to(user).filter(pk=item.pk).exists()
                }
                self.assertEqual(set(mentions.mentionable_people(item)), expected)

    def test_known_to_the_same_for_lists_and_querysets(self):
        """One rule: staff learn about everybody, clients and nobody in
        particular about the members"""
        people = User.objects.filter(pk__in=[self.ada.pk, self.bob.pk, self.cleo.pk])
        for viewer in [self.ada, self.cleo, AnonymousUser(), None]:
            with self.subTest(viewer=viewer):
                self.assertEqual(
                    set(self.project.people_known_to(viewer, people)),
                    set(mentions.known_to(people, self.project, viewer)),
                )
        self.assertEqual(
            set(self.project.people_known_to(None, people)), {self.ada, self.cleo}
        )

    def test_comment_mentions_notify_and_subscribe(self):
        unsubscribe(self.bob, self.todo)
        comment = ops.add_comment(
            self.todo,
            author=self.ada,
            content=f"Ask {mentions.syntax(self.bob)} and [@Dan](person:{self.dan.pk})",
        )
        # Dan can't see the project: not mentioned, not subscribed
        self.assertEqual(
            set(Mention.objects.values_list("user", flat=True)), {self.bob.pk}
        )
        self.assertEqual(Mention.objects.get().comment, comment)
        self.assertTrue(Subscription.objects.filter(user=self.bob).exists())
        self.assertFalse(Subscription.objects.filter(user=self.dan).exists())
        event = Event.objects.get(action=Action.COMMENTED)
        self.assertEqual(event.data["mentioned"], [self.bob.pk])

    def test_client_not_mentioned_on_internal_items(self):
        ops.add_comment(
            self.secret, author=self.ada, content=mentions.syntax(self.cleo)
        )
        self.assertFalse(Mention.objects.exists())
        rendered = markdown(mentions.syntax(self.cleo), self.secret)
        self.assertNotIn("wb-mention", rendered)
        self.assertIn("@Cleo", rendered)

    def test_only_new_mentions(self):
        ops.update_todo(
            self.todo, actor=self.ada, notes=f"For {mentions.syntax(self.bob)}"
        )
        event = Event.objects.get(action=Action.EDITED)
        self.assertEqual(event.data["mentioned"], [self.bob.pk])
        # Bob still mentioned, Cleo new
        newly = mentions.update(
            self.todo,
            f"{mentions.syntax(self.bob)} {mentions.syntax(self.cleo)}",
            actor=self.ada,
        )
        self.assertEqual(newly, [self.cleo])
        # Bob removed and mentioned again: new again
        mentions.update(self.todo, "nobody", actor=self.ada)
        self.assertEqual(
            mentions.update(self.todo, mentions.syntax(self.bob), actor=self.ada),
            [self.bob],
        )

    def test_mention_after_unsubscribing(self):
        ops.update_todo(self.todo, actor=self.ada, notes=mentions.syntax(self.bob))
        unsubscribe(self.bob, self.todo)
        # Still mentioned, the text edited: doesn't come back
        ops.update_todo(
            self.todo, actor=self.ada, notes=f"{mentions.syntax(self.bob)} again"
        )
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())
        # Mentioned in a comment: comes back
        ops.add_comment(self.todo, author=self.ada, content=mentions.syntax(self.bob))
        self.assertTrue(Subscription.objects.filter(user=self.bob).exists())

    def test_rendering_current_names(self):
        text = f"Hi [@Old Name](person:{self.bob.pk})"
        self.bob.full_name = "Bob Renamed"
        self.bob.short_name = "Bobby"
        self.bob.save()
        with mentions.reading_as(self.ada):
            rendered = markdown(text, self.todo)
            self.assertIn('title="Bob Renamed">@Bobby</a>', rendered)
            self.assertIn(f'href="/people/{self.bob.pk}/"', rendered)
            # Not a link where the text leaves the site (API, mails)
            self.assertIn(
                'class="wb-mention" title="Bob Renamed">@Bobby</span>',
                html(text, self.todo),
            )
            # Without the item, the label, never a link to person:
            self.assertIn("@Old Name", markdown(text))
            self.assertNotIn("person:", markdown(text))
            self.assertIn("@Bobby", html(text, self.todo))
            self.assertEqual(mentions.plain(text, self.todo), "Hi @Bobby")
            self.assertEqual(mentions.plain(text), "Hi @Old Name")
            # Inside code it stays code
            self.assertIn("person:", markdown(f"`{text}`", self.todo))
        # Bob isn't a member: clients, and nobody in particular, read the label
        with mentions.reading_as(self.cleo):
            self.assertEqual(mentions.plain(text, self.todo), "Hi @Old Name")
        self.assertEqual(mentions.plain(text, self.todo), "Hi @Old Name")

    def test_people_deactivated_later(self):
        """A mention of somebody deactivated since shows their current name,
        linked to their page and marked inactive like assignees; clients
        still only learn about members (Bob isn't one); mentioning them
        anew doesn't count"""
        text = f"Hi [@Old Name](person:{self.bob.pk})"
        self.bob.short_name = "Bobby"
        self.bob.is_active = False
        self.bob.save()
        with mentions.reading_as(self.ada):
            rendered = markdown(text, self.todo)
            self.assertIn(
                f'<a class="wb-mention wb-person-link" href="/people/{self.bob.pk}/"'
                ' title="Bob Example (inactive)">@Bobby</a>'
                ' <span class="text-body-secondary">(inactive)</span>',
                rendered,
            )
            self.assertIn("@Bobby", html(text, self.todo))
            self.assertEqual(mentions.plain(text, self.todo), "Hi @Bobby")
        with mentions.reading_as(self.cleo):
            self.assertEqual(mentions.plain(text, self.todo), "Hi @Old Name")
        ops.add_comment(self.todo, author=self.ada, content=text)
        self.assertFalse(Mention.objects.filter(user=self.bob).exists())

    def test_old_and_new_labels_show_the_short_name(self):
        """A stored label is only a fallback: the full name or the short
        one, as written, make no difference; the short name (else the first
        word of the full name) shows, the full name is the title"""
        new = mentions.syntax(self.bob)
        self.assertEqual(new, f"[@Bob](person:{self.bob.pk})")
        self.bob.short_name = "Bobby"
        self.assertEqual(mentions.syntax(self.bob), f"[@Bobby](person:{self.bob.pk})")
        old = f"[@Bob Example](person:{self.bob.pk})"
        with mentions.reading_as(self.ada):
            for text in (old, new):
                rendered = markdown(text, self.todo)
                self.assertIn(">@Bob</a>", rendered)
                self.assertIn('title="Bob Example"', rendered)
                self.assertEqual(mentions.plain(text, self.todo), "@Bob")

    def test_unknown_people_keep_the_written_label(self):
        """A client doesn't know Bob (not a member): the label as written,
        without the full name as title, also in excerpts"""
        text = f"Ask [@Bob Old](person:{self.bob.pk})"
        with mentions.reading_as(self.cleo):
            rendered = markdown(text, self.todo)
            self.assertIn("@Bob Old", rendered)
            self.assertNotIn("title=", rendered)
            self.assertNotIn("Example", rendered)
            self.assertEqual(excerpt(text, 200, self.todo), "Ask @Bob Old")
        with mentions.reading_as(self.ada):
            self.assertEqual(excerpt(text, 200, self.todo), "Ask @Bob")

    def test_titles(self):
        todo = ops.create_todo(
            todolist=self.shared,
            title=f"Call {mentions.syntax(self.cleo)}",
            creator=self.ada,
        )
        self.assertEqual(item_title(todo), "Call @Cleo")
        self.assertTrue(Mention.objects.filter(user=self.cleo, item=todo).exists())
        self.assertEqual(
            Event.objects.get(item=todo, action=Action.CREATED).data["mentioned"],
            [self.cleo.pk],
        )

    def test_resolve(self):
        text = (
            "@ada@example.org and @Cleo, @cleo@example.org, not @Nobody,"
            f" mail@example.org, {mentions.syntax(self.bob)}"
        )
        self.assertEqual(
            mentions.resolve(self.todo, text, author=self.ada),
            f"{mentions.syntax(self.ada)} and {mentions.syntax(self.cleo)},"
            f" {mentions.syntax(self.cleo)}, not @Nobody, mail@example.org,"
            f" {mentions.syntax(self.bob)}",
        )
        # Cleo can't see internal items; ambiguous names stay
        self.assertEqual(
            mentions.resolve(self.secret, "@Cleo", author=self.ada), "@Cleo"
        )
        person("Adele", short_name="Ada")
        self.assertEqual(mentions.resolve(self.todo, "@Ada", author=self.ada), "@Ada")

    def test_candidates(self):
        limited = project("Salaries", members=[self.ada, self.cleo], all_access=False)
        salaries = ops.create_list(project=limited, title="2027", creator=self.ada)
        result = mentions.candidates(salaries, "", for_user=self.ada)
        by_name = {r["name"]: r for r in result}
        self.assertTrue(by_name["Ada Example"]["available"])
        self.assertEqual(
            by_name["Bob Example"]["reason"], "not a member of this project"
        )
        self.assertEqual(by_name["Cleo Example"]["reason"], "can't see internal items")
        self.assertNotIn("Dan Example", by_name)
        # Available first
        self.assertEqual([r["available"] for r in result], [True, False, False])
        self.assertEqual(
            [r["name"] for r in mentions.candidates(salaries, "bo", for_user=self.ada)],
            ["Bob Example"],
        )
        # Clients: members only, no addresses, not by address
        result = mentions.candidates(self.todo, "", for_user=self.cleo)
        self.assertEqual({r["name"] for r in result}, {"Ada Example", "Cleo Example"})
        self.assertEqual({r["email"] for r in result}, {""})
        self.assertEqual(
            mentions.candidates(self.todo, "example.org", for_user=self.cleo), []
        )


class NewItemMentionsTest(TestCase):
    """The @ list of the new message, doc and file forms: who will see the
    item that doesn't exist yet"""

    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.dan = person("Dan", client=True)  # not a member
        self.project = project(members=[self.ada, self.cleo], all_access=False)
        self.bob = person("Bob")  # staff, not a member
        self.url = f"/projects/{self.project.pk}/mentionable/"
        self.shared = ops.create_folder(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_folder(
            project=self.project, title="Internal", creator=self.ada
        )

    def get(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return {r["name"]: r for r in response.json()}

    def test_internal_staff_only(self):
        result = self.get(self.ada)
        self.assertTrue(result["Ada Example"]["available"])
        self.assertEqual(result["Cleo Example"]["reason"], "can't see internal items")
        self.assertEqual(
            result["Bob Example"]["reason"], "not a member of this project"
        )

    def test_visible_adds_the_client_members(self):
        result = self.get(self.ada, visible="1")
        self.assertTrue(result["Cleo Example"]["available"])
        self.assertFalse(result["Bob Example"]["available"])
        self.assertNotIn("Dan Example", result)

    def test_the_folder_decides(self):
        result = self.get(self.ada, folder=self.shared.pk)
        self.assertTrue(result["Cleo Example"]["available"])
        result = self.get(self.ada, folder=self.internal.pk, visible="1")
        self.assertFalse(result["Cleo Example"]["available"])

    def test_clients_find_members_without_addresses(self):
        result = self.get(self.cleo)
        self.assertEqual(set(result), {"Ada Example", "Cleo Example"})
        self.assertTrue(result["Cleo Example"]["available"])
        self.assertEqual({r["email"] for r in result.values()}, {""})
        self.assertEqual(self.get(self.cleo, q="example.org"), {})
        self.assertEqual(self.get(self.cleo, q="Bob"), {})

    def test_no_access(self):
        for user in [self.bob, self.dan]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_folder_clients_cannot_see(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.url, {"folder": self.internal.pk})
        self.assertEqual(response.status_code, 404)
        other = project("Other", members=[self.ada])
        folder = ops.create_folder(project=other, title="F", creator=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(self.url, {"folder": folder.pk})
        self.assertEqual(response.status_code, 404)

    def test_a_folder_which_is_no_number(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url, {"folder": "x"})
        self.assertEqual(response.status_code, 404)

    def test_the_forms_use_it(self):
        self.client.force_login(self.ada)
        response = self.client.get(f"/projects/{self.project.pk}/messages/new/")
        self.assertContains(response, f'data-mentions="{self.url}"')


class ClientsKnowMembersTest(TestCase):
    """Clients learn about the project's members only (specs/access.md):
    their mentions of other staff stay text and notify nobody, and they
    read the label as written for those, never the current name. Ada is a
    member, Bob staff who isn't (all-access), Cleo a client member."""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )
        self.text = f"@Bob, @bob@example.org, [@x](person:{self.bob.pk}) and @Ada"

    def api(self, user, method, path, data):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        response = getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertLess(response.status_code, 300, response.content)
        return response.json()

    def assertOnlyAda(self, item, content):
        self.assertNotIn("Bob Example", content)
        self.assertIn(mentions.syntax(self.ada), content)
        self.assertEqual(
            set(Mention.objects.filter(item=item).values_list("user", flat=True)),
            {self.ada.pk},
        )
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())

    def test_api_texts_written_by_clients(self):
        comment = self.api(
            self.cleo, "post", f"items/{self.todo.pk}/comments/", {"content": self.text}
        )
        self.assertOnlyAda(self.todo, comment["content"])
        self.assertNotIn("Bob Example", comment["content_html"])

        Mention.objects.all().delete()
        todo = self.api(
            self.cleo,
            "post",
            f"lists/{self.shared.pk}/todos/",
            {"title": "Call @Bob", "notes": self.text},
        )
        self.assertEqual(todo["title"], "Call @Bob")
        self.assertOnlyAda(Item.objects.get(pk=todo["id"]), todo["notes"])
        todo = self.api(
            self.cleo, "patch", f"todos/{todo['id']}/", {"notes": f"{self.text}!"}
        )
        self.assertOnlyAda(Item.objects.get(pk=todo["id"]), todo["notes"])

        message = self.api(
            self.cleo,
            "post",
            f"projects/{self.project.pk}/messages/",
            {"title": "Hello", "content": self.text},
        )
        self.assertOnlyAda(Item.objects.get(pk=message["id"]), message["content"])
        message = self.api(
            self.cleo,
            "patch",
            f"messages/{message['id']}/",
            {"content": f"{self.text}!"},
        )
        self.assertOnlyAda(Item.objects.get(pk=message["id"]), message["content"])

    def test_staff_saving_later_doesnt_count_what_a_client_wrote(self):
        todo = ops.create_todo(
            todolist=self.shared,
            title="Call",
            notes=f"[@x](person:{self.bob.pk})",
            creator=self.cleo,
        )
        self.assertFalse(Mention.objects.filter(user=self.bob).exists())
        ops.update_todo(todo, actor=self.ada, title="Call them")
        ops.update_todo(todo, actor=self.ada, notes=f"[@x](person:{self.bob.pk})!")
        self.assertFalse(Mention.objects.filter(user=self.bob).exists())
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())
        # What staff add themselves counts
        eve = person("Eve")
        ops.update_todo(
            todo,
            actor=self.ada,
            notes=f"[@x](person:{self.bob.pk}) [@y](person:{eve.pk})",
        )
        self.assertTrue(Subscription.objects.filter(user=eve).exists())
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())

    def test_staff_still_mention_everybody(self):
        comment = self.api(
            self.ada, "post", f"items/{self.todo.pk}/comments/", {"content": "@Bob"}
        )
        self.assertEqual(comment["content"], mentions.syntax(self.bob))
        self.assertTrue(Subscription.objects.filter(user=self.bob).exists())

    def test_guessed_ids_on_the_page(self):
        self.client.force_login(self.cleo)
        self.client.post(
            self.todo.get_absolute_url(),
            {"form": "comment", "content": f"[@x](person:{self.bob.pk})"},
        )
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())
        self.assertFalse(Mention.objects.filter(user=self.bob).exists())
        page = self.client.get(self.todo.get_absolute_url())
        self.assertContains(page, "@x")
        self.assertNotContains(page, "Bob Example")

    def test_clients_read_the_label(self):
        """Wherever names show: pages, the API's ``*_html``, search,
        unsubscribing. Staff read the current name (their forms have the
        text as written, label included)."""
        ops.add_comment(
            self.todo,
            author=self.ada,
            content=f"Ask [@Bob Old](person:{self.bob.pk}) about tents",
        )
        todo = ops.create_todo(
            todolist=self.shared,
            title=f"Tents for [@Bob Old](person:{self.bob.pk})",
            creator=self.ada,
        )
        self.bob.full_name = "Bob Renamed"
        self.bob.save()
        for user, name in [(self.cleo, "Bob Old"), (self.ada, "Bob")]:
            with self.subTest(user=user):
                self.client.force_login(user)
                pages = [
                    self.client.get(self.todo.get_absolute_url()),
                    self.client.get(todo.get_absolute_url()),
                    self.client.get("/search/", {"q": "tents"}),
                    self.client.get(unsubscribe_url(user, todo)),
                ]
                data = self.api(user, "get", f"items/{self.todo.pk}/comments/", {})
                html = data["results"][0]["content_html"]
                self.assertIn(f"@{name}", html)
                for page in pages:
                    self.assertContains(page, f"@{name}")
                if user.is_client:
                    self.assertNotIn("Bob", html.replace("Bob Old", ""))
                    for page in pages:
                        self.assertNotContains(page, "Bob Renamed")

    def test_mails(self):
        subscribe(self.cleo, self.todo)
        subscribe(self.bob, self.todo)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(
                self.todo,
                author=self.ada,
                content=f"Ask [@Bob Old](person:{self.bob.pk})",
            )
        self.bob.full_name = "Bob Renamed"
        self.bob.save()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        messages = {message.to[0]: message for message in mail.outbox}
        for user, name, other in [
            (self.cleo, "Bob Old", "Bob Renamed"),
            (self.bob, "Bob", "Bob Old"),
        ]:
            with self.subTest(user=user):
                message = messages[user.email]
                for body in [message.body, message.alternatives[0][0]]:
                    self.assertIn(f"@{name}", body)
                    self.assertNotIn(other, body)
