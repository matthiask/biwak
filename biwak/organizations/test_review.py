"""Gaps the review of partners found (specs/access.md): who partners learn
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
from biwak.test_utils import organization, partner, person, project, rule_post


class ReviewTestCase(TestCase):
    """Ada (own staff) and Pia (a partner) in the all-access "Camp" with
    Cleo (a client); Bob is own staff, not a member"""

    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada", organization=self.own)
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.pia = partner("Pia")
        self.camp = project("Camp", members=[self.ada, self.pia, self.cleo])
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
    def test_partners_are_offered_members_only(self):
        self.client.force_login(self.pia)
        url = f"/projects/{self.camp.pk}/checkins/new/"
        response = self.client.get(url)
        self.assertContains(response, "Ada Example")
        self.assertNotContains(response, "Bob Example")
        data = {
            "title": "How is it?",
            **rule_post(MONDAY_9["rule"], "rule"),
            "starts_on": "2027-03-15",
            "time_of_day": "09:00",
            "time_zone": "Europe/Zurich",
            "people": [self.bob.pk],
        }
        self.client.post(url, data)
        self.assertFalse(
            checkin_ops.Question.objects.filter(item__title="How is it?").exists()
        )

    def test_partners_keep_non_members_already_asked(self):
        item = self.question([self.ada, self.bob])
        checkin_ops.set_people(item, [self.ada, self.bob, self.pia], actor=self.pia)
        self.assertEqual(
            set(item.question.people.all()), {self.ada, self.bob, self.pia}
        )
        gus = person("Gus")
        with self.assertRaises(ValueError):
            checkin_ops.set_people(item, [self.ada, gus], actor=self.pia)


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

    def test_partners_ask_members_only_and_learn_no_names(self):
        bob = self.call(self.pia, {"people": [self.bob.pk]})
        self.assertEqual(bob.status_code, 400)
        self.assertNotIn("Bob", bob.json()["detail"])
        nobody = self.call(self.pia, {"people": [999999]})
        # Somebody who exists and somebody who doesn't: the same answer
        self.assertEqual(nobody.json(), bob.json())
        self.assertEqual(
            self.call(self.pia, {"people": [self.ada.pk]}).status_code, 201
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
    def test_partners_dont_learn_names_of_non_members(self):
        LoggedAction.objects.all().delete()
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Membership.objects.filter(project=self.camp, user=self.bob).delete()
        ops.assign(self.todo, [self.pia], actor=self.ada)
        shown = {
            c.new for c in history.history(self.todo, self.pia) if c.kind == "assigned"
        }
        self.assertEqual(shown, {"Pia Example", "somebody"})
        shown = {
            c.new for c in history.history(self.todo, self.ada) if c.kind == "assigned"
        }
        self.assertEqual(shown, {"Pia Example", "Bob Example"})


class NamesTest(ReviewTestCase):
    def test_mails_name_whom_the_reader_may_know(self):
        Membership.objects.create(project=self.camp, user=self.bob)
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Membership.objects.filter(project=self.camp, user=self.bob).delete()
        ids = [self.bob.pk, self.ada.pk]
        self.assertEqual(_names(ids, self.pia, self.todo), "Ada Example")
        self.assertEqual(_names(ids, self.cleo, self.todo), "Ada Example")
        self.assertEqual(_names(ids, self.root, self.todo), "Ada Example, Bob Example")

    def test_the_feed_names_whom_the_reader_may_know(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        # Assigning made him a member; not anymore
        Membership.objects.filter(project=self.camp, user=self.bob).delete()
        events = list(Event.objects.filter(action=Action.ASSIGNED))
        feed.attach(events, self.pia)
        self.assertEqual(events[0].assignee_names, [])
        feed.attach(events, self.ada)
        self.assertEqual(events[0].assignee_names, ["Bob"])

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

    def test_moved_to_a_partner_organization(self):
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
    def test_a_partner_creator_keeps_assignees_and_mentions(self):
        with importing():
            ops.assign(self.todo, [self.bob], actor=self.pia)
            mentioned = mentions.update(
                self.todo, mentions.syntax(self.bob), actor=self.pia
            )
        self.assertIn(self.bob, self.todo.todo.assignees.all())
        self.assertEqual(mentioned, [self.bob])
