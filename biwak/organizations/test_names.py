"""People with the same first name (specs/ui-round-2.md, part F)"""

from django.db import connection
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from biwak.accounts.models import User
from biwak.activity import mentions
from biwak.items import operations as ops
from biwak.organizations.models import Organization
from biwak.organizations.names import display_name, display_names
from biwak.templatetags.biwak import excerpt, markdown
from biwak.test_utils import person, project


def named(full_name, **kwargs):
    kwargs.setdefault("organization", Organization.objects.own())
    return User.objects.create_user(
        f"{full_name.lower().replace(' ', '.')}@example.org",
        full_name=full_name,
        **kwargs,
    )


class DisplayNamesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.fischer = named("Moritz Fischer")
        self.meier = named("Moritz Meier")
        self.client_moritz = named("Moritz Zimmer", is_client=True)
        self.project = project(members=[self.ada, self.fischer, self.client_moritz])
        self.todo = ops.create_todo(
            todolist=ops.create_list(
                project=self.project, title="L", creator=self.ada, visible=True
            ),
            title="T",
            creator=self.ada,
        )

    def names(self, viewer):
        # A fresh object: the names are computed once per viewer object
        return display_names(User.objects.get(pk=viewer.pk))

    def test_the_initial_of_the_last_name_tells_them_apart(self):
        """Own staff know everybody; two Moritzes with the same initial
        both get the full name"""
        names = self.names(self.ada)
        self.assertEqual(names[self.ada.pk], "Ada")
        self.assertEqual(names[self.meier.pk], "Moritz M.")
        # Fischer and Frei both start with F
        self.assertEqual(names[self.fischer.pk], "Moritz F.")
        self.assertEqual(names[self.client_moritz.pk], "Moritz Z.")
        frei = named("Moritz Frei")
        names = self.names(self.ada)
        self.assertEqual(names[self.fischer.pk], "Moritz Fischer")
        self.assertEqual(names[frei.pk], "Moritz Frei")
        self.assertEqual(names[self.meier.pk], "Moritz M.")

    def test_two_with_different_initials(self):
        self.client_moritz.delete()
        names = self.names(self.ada)
        self.assertEqual(names[self.fischer.pk], "Moritz F.")
        self.assertEqual(names[self.meier.pk], "Moritz M.")

    def test_the_viewer_only_counts_people_they_may_know(self):
        """A client knows the project's members: Fischer is the only
        Moritz they know besides themselves"""
        names = self.names(self.client_moritz)
        self.assertEqual(names[self.fischer.pk], "Moritz F.")
        self.assertEqual(names[self.client_moritz.pk], "Moritz Z.")
        self.assertNotIn(self.meier.pk, names)
        # Meier would be "Moritz M." to staff, and a Moritz alone is "Moritz"
        self.project.memberships.filter(user=self.fischer).delete()
        names = self.names(self.client_moritz)
        self.assertEqual(names[self.client_moritz.pk], "Moritz")
        # Alone, a name stays short
        client = person("Cleo", client=True)
        self.assertEqual(self.names(client), {client.pk: "Cleo"})

    def test_an_explicit_short_name_counts(self):
        self.fischer.short_name = "Fritz"
        self.fischer.save()
        self.client_moritz.delete()
        names = self.names(self.ada)
        self.assertEqual(names[self.fischer.pk], "Fritz")
        self.assertEqual(names[self.meier.pk], "Moritz")

    def test_no_last_name_gets_the_full_name(self):
        single = named("Moritz")
        names = self.names(self.ada)
        self.assertEqual(names[single.pk], "Moritz")
        self.assertEqual(names[self.meier.pk], "Moritz M.")

    def test_nobody_and_strangers_fall_back_to_the_short_name(self):
        self.assertEqual(display_names(None), {})
        self.assertEqual(display_name(self.meier, None), "Moritz")
        client = person("Cleo", client=True)
        self.assertEqual(
            display_name(self.meier, User.objects.get(pk=client.pk)), "Moritz"
        )

    def test_computed_once_per_viewer(self):
        viewer = User.objects.get(pk=self.ada.pk)
        display_name(self.ada, viewer)
        with self.assertNumQueries(0):
            for _i in range(10):
                for user in (self.fischer, self.meier, self.ada):
                    display_name(user, viewer)

    def test_mentions_show_the_name_the_reader_sees(self):
        text = (
            f"[@Moritz Fischer](person:{self.fischer.pk}) and"
            f" [@Moritz](person:{self.meier.pk})"
        )
        with mentions.reading_as(User.objects.get(pk=self.ada.pk)):
            rendered = markdown(text, self.todo)
            self.assertIn(">@Moritz F.</a>", rendered)
            self.assertIn('title="Moritz Fischer"', rendered)
        # Fischer is a member, Meier is not: the client knows only Fischer
        # (and themselves, also a Moritz)
        with mentions.reading_as(User.objects.get(pk=self.client_moritz.pk)):
            self.assertIn(">@Moritz F.</a>", markdown(text, self.todo))
            self.assertEqual(excerpt(text, 200, self.todo), "@Moritz F. and @Moritz")

    def test_plain_texts_and_mails(self):
        """Mails are rendered with the recipient as reader"""
        text = f"Ask [@Moritz](person:{self.meier.pk})"
        self.project.memberships.create(user=self.meier)
        self.client_moritz.delete()
        with mentions.reading_as(User.objects.get(pk=self.ada.pk)):
            self.assertEqual(mentions.plain(text, self.todo), "Ask @Moritz M.")
        # The label as written for nobody in particular
        self.assertEqual(mentions.plain(text, self.todo), "Ask @Moritz")

    def test_the_syntax_and_the_list_use_the_name_of_the_one_typing(self):
        self.client_moritz.delete()
        ada = User.objects.get(pk=self.ada.pk)
        self.assertEqual(
            mentions.syntax(self.fischer, ada),
            f"[@Moritz F.](person:{self.fischer.pk})",
        )
        listed = mentions.candidates(self.todo, "Moritz", for_user=ada)
        self.assertEqual(
            {r["name"]: r["short_name"] for r in listed},
            {"Moritz Fischer": "Moritz F.", "Moritz Meier": "Moritz M."},
        )
        # An API text typed with a short name which isn't unique stays
        self.assertEqual(mentions.resolve(self.todo, "@Moritz", author=ada), "@Moritz")

    def test_templates(self):
        request = RequestFactory().get("/")
        request.user = User.objects.get(pk=self.ada.pk)
        html = Template(
            "{% load biwak %}{% short_name a %}, {% short_name b %}, {% short_name c %}"
        ).render(
            Context({
                "request": request,
                "a": self.ada,
                "b": self.fischer,
                "c": self.meier,
            })
        )
        self.assertEqual(html, "Ada, Moritz F., Moritz M.")

    def test_pages(self):
        """The assignees of a to-do: staff know both Moritzes, a client
        member only the one in the project"""
        self.client_moritz.delete()
        cleo = person("Cleo", client=True)
        self.project.memberships.create(user=cleo)
        ops.assign(self.todo, [self.fischer], actor=self.ada)
        url = self.todo.get_absolute_url()
        self.client.force_login(self.ada)
        html = self.client.get(url).content.decode()
        self.assertIn("Moritz F.", html)
        self.assertNotIn("Moritz Meier", html)
        self.client.force_login(cleo)
        html = self.client.get(url).content.decode()
        self.assertNotIn("Moritz F.", html)
        self.assertIn("Moritz", html)
        # Now both are in the project: the client tells them apart too
        ops.assign(self.todo, [self.fischer, self.meier], actor=self.ada)
        html = self.client.get(url).content.decode()
        self.assertIn("Moritz F.", html)
        self.assertIn("Moritz M.", html)

    def test_the_number_of_queries_doesnt_grow_with_the_people(self):
        self.client_moritz.delete()
        self.client.force_login(self.ada)
        url = self.todo.get_absolute_url()
        ops.assign(self.todo, [self.fischer, self.meier], actor=self.ada)
        self.client.get(url)  # warm caches
        with CaptureQueriesContext(connection) as few:
            self.client.get(url)
        more = [named(f"Moritz {name}") for name in "Abcdef"]
        ops.assign(self.todo, [self.fischer, self.meier, *more], actor=self.ada)
        with CaptureQueriesContext(connection) as many:
            self.client.get(url)
        self.assertEqual(len(few), len(many))
