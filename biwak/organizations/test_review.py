"""Gaps the review of externals found (specs/access.md): who externals learn
about through check-ins, the history, mails and the feed; subscriptions
when leaving the own organization; the importer"""

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.activity import feed, history, mentions
from biwak.activity.mails import _names
from biwak.activity.models import Action, Event, Subscription
from biwak.activity.operations import importing, subscribe
from biwak.audit.models import LoggedAction
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9
from biwak.items import operations as ops
from biwak.organizations import operations as org_ops
from biwak.projects.models import Membership
from biwak.test_utils import external, organization, person, project, rule_post


class ReviewTestCase(TestCase):
    """Ada (own staff) and Pia (an external) in the all-access "Camp" with
    Cleo (a client); Bob is own staff, not a member, whom Pia knows as one
    of Camp's people (decided 2026-11-21); Paul is an external of another
    project, whom she doesn't"""

    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada", organization=self.own)
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.pia = external("Pia")
        self.paul = external("Paul", organization_name="Example Other Agency")
        self.camp = project("Camp", members=[self.ada, self.pia, self.cleo])
        self.lake = project("Lake", members=[self.paul])
        self.tents = ops.create_list(project=self.camp, title="Tents", creator=self.ada)
        self.todo = ops.create_todo(
            todolist=self.tents, title="Pitch the tents", creator=self.ada
        )

    def question(self, people):
        return checkin_ops.create_question(
            project=self.camp,
            title="How is the camp?",
            creator=self.ada,
            people=people,
            **MONDAY_9,
        )


class CheckinFormTest(ReviewTestCase):
    def data(self, people):
        return {
            "title": "How is it?",
            **rule_post(MONDAY_9["rule"], "rule"),
            "starts_on": "2027-03-15",
            "time_of_day": "09:00",
            "people": people,
        }

    def test_externals_are_offered_the_project_s_people(self):
        self.client.force_login(self.pia)
        url = f"/projects/{self.camp.pk}/checkins/new/"
        response = self.client.get(url)
        self.assertContains(response, "Ada Example")
        self.assertContains(response, "Bob Example")
        self.assertNotContains(response, "Paul Example")
        self.client.post(url, self.data([self.paul.pk]))
        self.assertFalse(
            checkin_ops.Question.objects.filter(item__title="How is it?").exists()
        )
        self.client.post(url, self.data([self.bob.pk]))
        question = checkin_ops.Question.objects.get(item__title="How is it?")
        self.assertEqual(set(question.people.all()), {self.bob})

    def test_externals_ask_the_project_s_people(self):
        item = self.question([self.ada])
        gus = person("Gus")  # own staff, not a member either
        checkin_ops.set_people(item, [self.ada, self.bob, gus], actor=self.pia)
        self.assertEqual(set(item.question.people.all()), {self.ada, self.bob, gus})
        with self.assertRaises(ValueError):
            checkin_ops.set_people(item, [self.ada, self.paul], actor=self.pia)


class CheckinAPITest(ReviewTestCase):
    def call(self, user, data):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return self.client.post(
            f"/api/v1/projects/{self.camp.pk}/checkins/",
            {"title": "How is it?", "schedule": "weekly", "time_of_day": "09:00"}
            | data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_externals_ask_the_project_s_people_and_learn_no_names(self):
        paul = self.call(self.pia, {"people": [self.paul.pk]})
        self.assertEqual(paul.status_code, 400)
        self.assertNotIn("Paul", paul.json()["detail"])
        nobody = self.call(self.pia, {"people": [999999]})
        # Somebody who exists and somebody who doesn't: the same answer
        self.assertEqual(nobody.json(), paul.json())
        self.assertEqual(
            self.call(self.pia, {"people": [self.ada.pk, self.bob.pk]}).status_code,
            201,
        )

    def test_names_never_in_the_message(self):
        """Own staff asking a client on an internal question: no name"""
        response = self.call(self.ada, {"people": [self.cleo.pk]})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Cleo", response.json()["detail"])

    def test_clients_dont_ask(self):
        response = self.call(self.cleo, {"people": [self.bob.pk]})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Bob", response.content.decode())


class HistoryTest(ReviewTestCase):
    def test_externals_learn_the_names_of_the_project_s_people_only(self):
        """Bob (own staff) and Paul (an external) were members and left:
        Bob still opens the all-access project, Paul doesn't"""
        LoggedAction.objects.all().delete()
        Membership.objects.create(project=self.camp, user=self.paul)
        ops.assign(self.todo, [self.bob, self.paul], actor=self.ada)
        Membership.objects.filter(
            project=self.camp, user__in=[self.bob, self.paul]
        ).delete()
        ops.assign(self.todo, [self.pia], actor=self.ada)

        def shown(viewer):
            return {
                c.new
                for c in history.history(self.todo, viewer)
                if c.kind == "assigned"
            }

        self.assertEqual(shown(self.pia), {"Pia Example", "Bob Example", "somebody"})
        self.assertEqual(
            shown(self.ada), {"Pia Example", "Bob Example", "Paul Example"}
        )


class NamesTest(ReviewTestCase):
    def test_mails_name_whom_the_reader_may_know(self):
        Membership.objects.create(project=self.camp, user=self.paul)
        ops.assign(self.todo, [self.bob, self.paul], actor=self.ada)
        Membership.objects.filter(
            project=self.camp, user__in=[self.bob, self.paul]
        ).delete()
        ids = [self.bob.pk, self.paul.pk, self.ada.pk]
        self.assertEqual(_names(ids, self.pia, self.todo), "Ada Example, Bob Example")
        self.assertEqual(_names(ids, self.cleo, self.todo), "Ada Example")
        self.assertEqual(
            _names(ids, self.root, self.todo),
            "Ada Example, Bob Example, Paul Example",
        )

    def test_the_feed_names_whom_the_reader_may_know(self):
        Membership.objects.create(project=self.camp, user=self.paul)
        ops.assign(self.todo, [self.bob, self.paul], actor=self.ada)
        # Assigning made Bob a member; neither is one anymore
        Membership.objects.filter(
            project=self.camp, user__in=[self.bob, self.paul]
        ).delete()
        events = list(Event.objects.filter(action=Action.ASSIGNED))
        feed.attach(events, self.pia)
        self.assertEqual(events[0].assignee_names, ["Bob"])
        feed.attach(events, self.cleo)
        self.assertEqual(events[0].assignee_names, [])
        feed.attach(events, self.ada)
        self.assertEqual(events[0].assignee_names, ["Bob", "Paul"])

    def test_the_feed_keeps_the_old_list_title_for_own_staff_only(self):
        lodge = project("Lodge", members=[self.ada])
        rooms = ops.create_list(project=lodge, title="Rooms", creator=self.ada)
        event = Event.objects.create(
            project=self.camp,
            item=self.todo,
            actor=self.ada,
            action=Action.MOVED,
            data={"to": "Rooms", "to_id": rooms.pk},
        )
        feed.add_target_lists([event], self.pia)
        self.assertEqual(event.target_list, "")
        feed.add_target_lists([event], self.bob)
        self.assertEqual(event.target_list, "Rooms")


class SubscriptionsTest(ReviewTestCase):
    """Leaving the own organization loses access to
    all-access projects one isn't a member of: their subscriptions go"""

    def setUp(self):
        super().setUp()
        self.lodge = project("Lodge", members=[self.root])
        rooms = ops.create_list(project=self.lodge, title="Rooms", creator=self.root)
        self.book = ops.create_todo(todolist=rooms, title="Book", creator=self.root)
        subscribe(self.bob, self.book)
        subscribe(self.bob, self.todo)

    def subscribed(self):
        return set(
            Subscription.objects.filter(user=self.bob).values_list("item", flat=True)
        )

    def test_moved_to_an_external_organization(self):
        org_ops.set_organization(
            self.bob, organization("Example Agency"), actor=self.root
        )
        self.assertEqual(self.subscribed(), set())

    def test_members_keep_theirs(self):
        Membership.objects.create(project=self.lodge, user=self.bob)
        org_ops.set_organization(
            self.bob, organization("Example Agency"), actor=self.root
        )
        self.assertEqual(self.subscribed(), {self.book.pk})

    def test_an_individual_now(self):
        org_ops.set_organization(self.bob, None, actor=self.root)
        self.assertEqual(self.subscribed(), set())


class ImporterTest(ReviewTestCase):
    def test_an_external_creator_keeps_assignees_and_mentions(self):
        with importing():
            ops.assign(self.todo, [self.bob], actor=self.pia)
            mentioned = mentions.update(
                self.todo, mentions.syntax(self.bob), actor=self.pia
            )
        self.assertIn(self.bob, self.todo.todo.assignees.all())
        self.assertEqual(mentioned, [self.bob])
