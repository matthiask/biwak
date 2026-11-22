import datetime as dt

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from biwak.accounts.models import NotificationLevel
from biwak.activity import mentions
from biwak.activity.mails import _deliverable
from biwak.activity.models import (
    Action,
    Event,
    LevelOverride,
    Mention,
    Notification,
    Subscription,
)
from biwak.activity.notify import (
    can_see,
    effective_level,
    everybody,
    notify,
    notify_people,
    told_by_default,
    told_line,
    who_can_see,
)
from biwak.activity.operations import (
    record,
    set_level_override,
    subscribe,
    unsubscribe,
)
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects import operations as project_ops
from biwak.test_utils import external, organization, person, project


class NotifyTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
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

    def told(self, run):
        """Runs ``run`` and the notifications after the commit; who was told"""
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            run()
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }

    def test_comment(self):
        subscribe(self.bob, self.todo)
        subscribe(self.cleo, self.todo)
        told = self.told(
            lambda: ops.add_comment(self.todo, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob, self.cleo})
        # Never the actor
        told = self.told(
            lambda: ops.add_comment(self.todo, author=self.bob, content="Hi")
        )
        self.assertEqual(told, {self.ada, self.cleo})

    def test_client_not_told_about_internal_items(self):
        subscribe(self.cleo, self.secret)  # e.g. before it was hidden
        subscribe(self.bob, self.secret)
        told = self.told(
            lambda: ops.add_comment(self.secret, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob})

    def test_lost_access(self):
        """Visibility is checked when notifying, not when subscribing"""
        subscribe(self.cleo, self.todo)
        subscribe(self.bob, self.todo)
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        told = self.told(
            lambda: ops.add_comment(self.todo, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob})
        limited = project("Salaries", members=[self.ada, self.bob], all_access=False)
        salaries = ops.create_list(project=limited, title="2027", creator=self.ada)
        subscribe(self.bob, salaries)
        project_ops.remove_member(limited, self.bob, actor=self.ada)
        subscribe(self.bob, salaries)  # even if the subscription stayed
        self.assertEqual(
            self.told(lambda: ops.update_list(salaries, actor=self.ada, title="X")),
            set(),
        )

    def test_inactive_not_told(self):
        subscribe(self.bob, self.todo)
        self.bob.is_active = False
        self.bob.save()
        self.assertEqual(
            self.told(lambda: ops.add_comment(self.todo, author=self.ada, content="x")),
            set(),
        )

    def test_created_tells_container_subscribers(self):
        subscribe(self.bob, self.shared)
        told = self.told(
            lambda: ops.create_todo(todolist=self.shared, title="New", creator=self.ada)
        )
        self.assertEqual(told, {self.bob})

    def test_assigned_and_completed(self):
        told = self.told(lambda: ops.assign(self.todo, [self.bob], actor=self.ada))
        self.assertEqual(told, {self.bob})
        told = self.told(lambda: ops.complete(self.todo, actor=self.bob))
        self.assertEqual(told, {self.ada})
        told = self.told(lambda: ops.reopen(self.todo, actor=self.ada))
        self.assertEqual(told, {self.bob})

    def test_other_events(self):
        subscribe(self.bob, self.shared)
        subscribe(self.bob, self.todo)
        self.assertTrue(
            self.told(
                lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada)
            )
        )
        # Moving tells nobody (decided 2026-11-22, specs/handover.md)
        for action in [
            lambda: ops.move_todo(self.todo, todolist=self.internal, actor=self.ada),
            lambda: ops.move_todo(self.todo, todolist=self.shared, actor=self.ada),
        ]:
            with self.subTest(action=action):
                self.assertEqual(self.told(action), set())
        # Trashed: nobody can see it any more, nobody is told
        self.assertEqual(self.told(lambda: ops.trash(self.todo, actor=self.ada)), set())
        self.assertEqual(
            self.told(lambda: ops.restore(self.todo, actor=self.ada)), {self.bob}
        )

    def test_archiving_a_list_notifies_nobody(self):
        subscribe(self.bob, self.shared)
        self.assertEqual(
            self.told(lambda: ops.archive(self.shared, actor=self.ada)), set()
        )
        self.assertEqual(
            self.told(lambda: ops.unarchive(self.shared, actor=self.ada)), set()
        )

    def test_project_events_notify_nobody(self):
        dan = person("Dan")
        self.assertEqual(
            self.told(
                lambda: project_ops.add_member(self.project, dan, actor=self.ada)
            ),
            set(),
        )
        event = record(actor=self.ada, action=Action.JOINED, project=self.project)
        self.assertEqual(notify(event.pk), [])

    def test_subscribed_means_everything(self):
        """Subscribing is the switch (specs/notifications.md, "Subscriptions"): whatever
        the level, a subscriber is told about everything on the item; not
        subscribed, nothing but a mention"""
        comment = lambda: ops.add_comment(self.todo, author=self.ada, content="x")  # noqa: E731
        for level in NotificationLevel:
            edit = lambda level=level: ops.update_todo(  # noqa: E731
                self.todo, actor=self.ada, title=f"New {level}"
            )
            with self.subTest(level=level):
                self.bob.notification_level = level
                self.bob.save()
                subscribe(self.bob, self.todo)
                self.assertEqual(self.told(comment), {self.bob})
                Notification.objects.all().delete()
                self.assertEqual(self.told(edit), {self.bob})
                Notification.objects.all().delete()
                unsubscribe(self.bob, self.todo)
                self.assertEqual(self.told(comment), set())

    def test_mentions_on_every_level(self):
        """Mentions are someone deliberately asking for you (decided
        2026-11-22): they tell and subscribe on every level"""
        mention = lambda: ops.add_comment(  # noqa: E731
            self.todo, author=self.ada, content=mentions.syntax(self.bob)
        )
        for level in NotificationLevel:
            with self.subTest(level=level):
                self.bob.notification_level = level
                self.bob.save()
                Mention.objects.all().delete()
                Subscription.objects.filter(user=self.bob).delete()
                self.assertEqual(self.told(mention), {self.bob})
                # Subscribed by it: the next comment tells them
                self.assertEqual(
                    self.told(
                        lambda: ops.add_comment(self.todo, author=self.ada, content="x")
                    ),
                    {self.bob},
                )

    def test_what_they_do_subscribes_them_on_concerns_me(self):
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        comment = lambda: ops.add_comment(self.todo, author=self.ada, content="x")  # noqa: E731
        self.assertEqual(self.told(comment), set())
        # Commenting
        ops.add_comment(self.todo, author=self.bob, content="me too")
        self.assertEqual(self.told(comment), {self.bob})
        # Being assigned, and told so
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        self.assertEqual(
            self.told(lambda: ops.assign(other, [self.bob], actor=self.ada)),
            {self.bob},
        )
        self.assertEqual(
            self.told(lambda: ops.complete(other, actor=self.ada)), {self.bob}
        )

    def test_new_to_dos_in_a_list_by_its_level(self):
        """Subscribed to a list, the level for it decides whether a new to-do
        in it tells the person: "everything" does, the others don't"""
        subscribe(self.bob, self.shared)
        new = lambda: ops.create_todo(  # noqa: E731
            todolist=self.shared, title="New", creator=self.ada
        )
        self.assertEqual(self.told(new), {self.bob})
        LevelOverride.objects.create(
            user=self.bob, project=self.project, level=NotificationLevel.CONCERNS_ME
        )
        self.assertEqual(self.told(new), set())
        # The list's level wins over the project's
        set_level_override(self.bob, NotificationLevel.EVERYTHING, item=self.shared)
        self.assertEqual(effective_level(self.bob, self.todo), "everything")
        self.assertEqual(self.told(new), {self.bob})
        set_level_override(self.bob, NotificationLevel.CONCERNS_ME, item=self.shared)
        self.assertEqual(self.told(new), set())
        # Mentioned in the new one: told
        self.assertEqual(
            self.told(
                lambda: ops.create_todo(
                    todolist=self.shared,
                    title=f"For {mentions.syntax(self.bob)}",
                    creator=self.ada,
                )
            ),
            {self.bob},
        )

    def test_only_lists_have_levels(self):
        with self.assertRaisesMessage(ValueError, "Only lists have a level"):
            set_level_override(self.bob, NotificationLevel.CONCERNS_ME, item=self.todo)
        self.assertIsNotNone(
            set_level_override(
                self.bob, NotificationLevel.CONCERNS_ME, item=self.shared
            )
        )

    def test_edits_merge(self):
        subscribe(self.bob, self.todo)
        told = self.told(
            lambda: ops.update_todo(self.todo, actor=self.ada, title="One")
        )
        self.assertEqual(told, {self.bob})
        first = Notification.objects.get()
        self.told(lambda: ops.update_todo(self.todo, actor=self.ada, title="Two"))
        event = Event.objects.get(action=Action.EDITED)
        self.assertEqual(event.data["title"], "Two")
        # Still one, unsent notification, moved forward
        notification = Notification.objects.get()
        self.assertGreater(notification.created_at, first.created_at)
        # Sent: the session goes on without telling Bob again
        Notification.objects.update(sent_at=timezone.now())
        self.told(lambda: ops.update_todo(self.todo, actor=self.ada, title="Three"))
        self.assertEqual(Notification.objects.count(), 1)
        # Unless he's mentioned now
        self.told(
            lambda: ops.update_todo(
                self.todo, actor=self.ada, notes=mentions.syntax(self.bob)
            )
        )
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 2)
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 1)
        # After 10 minutes, or by someone else, a new event
        Event.objects.filter(action=Action.EDITED).update(
            created_at=timezone.now() - dt.timedelta(minutes=11)
        )
        ops.update_todo(self.todo, actor=self.ada, title="Four")
        ops.update_todo(self.todo, actor=self.bob, title="Five")
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 3)

    def test_one_unsent_notification_per_person_and_event(self):
        """Two notify() at once (two quick edits merged into one event) can't
        tell anybody twice: the database refuses a second unsent one"""
        subscribe(self.bob, self.todo)
        self.told(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        notification = Notification.objects.get(user=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Notification.objects.create(user=self.bob, event=notification.event)
        # Once sent, the next one may come
        Notification.objects.update(sent_at=timezone.now())
        Notification.objects.create(user=self.bob, event=notification.event)

    def test_notify_people(self):
        """Those told by default, and the people added who can see it"""
        message = ops.create_message(
            project=self.project, title="News", creator=self.ada
        )
        # Bob wants everything; Cleo can't see the internal message
        self.assertEqual(
            set(
                Subscription.objects.filter(item=message).values_list("user", flat=True)
            ),
            {self.ada.pk, self.bob.pk},
        )
        unsubscribe(self.bob, message)
        self.assertEqual(
            notify_people(message, also=[self.bob, self.cleo], actor=self.ada),
            [self.bob],
        )

    def test_posting_per_level(self):
        """Posting tells those on "everything" (specs/notifications.md,
        "Subscriptions"); people added by name whatever their level"""
        dan, eve = person("Dan"), person("Eve")
        for user in [dan, eve]:
            project_ops.add_member(self.project, user, actor=self.ada)
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        project_ops.set_notify_choice(
            self.project, dan, project_ops.NOTIFY_TAGGED, actor=self.ada
        )
        # Bob's own level is "concerns me", but the project's choice "notified
        # by default" (adding him stored it) wins
        LevelOverride.objects.filter(user=self.bob).delete()
        told = self.told(
            lambda: ops.create_message(
                project=self.project, title="News", creator=self.ada, visible=True
            )
        )
        self.assertEqual(told, {self.cleo, eve})
        message = Item.objects.get(title="News")
        self.assertEqual(
            notify_people(message, also=[self.bob, dan], actor=self.ada),
            [self.cleo, eve, self.bob, dan],
        )


class ToldByDefaultTest(TestCase):
    """Whom something new tells without the poster choosing (decided
    2026-11-21: additive): the container's subscribers and those on
    "everything", who see it, never the poster"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.dan = person("Dan")
        self.project = project(members=[self.ada, self.bob, self.cleo, self.dan])
        for user in [self.bob, self.cleo, self.dan]:
            user.notification_level = NotificationLevel.CONCERNS_ME
            user.save()
        self.folder = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada, visible=True
        )

    def test_the_level_and_the_folders_subscribers(self):
        self.assertEqual(
            told_by_default(self.project, self.folder, visible=True, actor=self.bob),
            [self.ada],
        )
        subscribe(self.dan, self.folder)
        subscribe(self.cleo, self.folder)
        self.assertEqual(
            told_by_default(self.project, self.folder, visible=True, actor=self.bob),
            [self.ada, self.cleo, self.dan],
        )
        # Never the poster; clients only what they see
        self.assertEqual(
            told_by_default(self.project, self.folder, visible=False, actor=self.ada),
            [self.dan],
        )

    def test_creating_a_folder_doesnt_subscribe_its_creator(self):
        """Creating a folder is housekeeping, not following it: on "only
        what concerns me" its creator isn't told about new files (decided
        2026-11-22)"""
        folder = ops.create_folder(
            project=self.project, title="Drafts", creator=self.bob
        )
        self.assertFalse(Subscription.objects.filter(item=folder).exists())
        self.assertEqual(
            told_by_default(self.project, folder, visible=False, actor=self.dan),
            [self.ada],  # on "everything"
        )

    def test_posting_into_the_folder_tells_them(self):
        subscribe(self.dan, self.folder)
        with self.captureOnCommitCallbacks(execute=True):
            ops.create_doc(
                project=self.project,
                title="Notes",
                creator=self.bob,
                parent=self.folder,
            )
        self.assertEqual(
            set(Notification.objects.values_list("user", flat=True)),
            {self.ada.pk, self.dan.pk},
        )

    def test_the_line(self):
        people = [self.ada, self.bob, self.cleo, self.dan]
        self.assertEqual(
            told_line([], self.project, self.ada),
            "Nobody is told unless you add people.",
        )
        self.assertEqual(
            told_line(people[:3], self.project, self.dan),
            "Ada, Bob and Cleo will be told.",
        )
        self.assertEqual(
            told_line(people, self.project, self.dan),
            "Ada, Bob and 2 others will be told.",
        )
        # Names the poster may know: a client knows the members only
        outsider = person("Eve")
        self.assertEqual(
            told_line([outsider, self.ada], self.project, self.cleo),
            "Ada and 1 other will be told.",
        )


class EverybodyTest(TestCase):
    """The members on "everything" who see it, also before the item exists
    (``told_by_default()``)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        # Own staff see all-access projects, but aren't members
        person("Dan")

    def test_members_who_see_it(self):
        self.assertEqual(
            set(everybody(self.project, visible=False)), {self.ada, self.bob}
        )
        self.assertEqual(
            set(everybody(self.project, visible=True)),
            {self.ada, self.bob, self.cleo},
        )

    def test_on_everything_only(self):
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        set_level_override(
            self.cleo, NotificationLevel.CONCERNS_ME, project=self.project
        )
        self.assertEqual(everybody(self.project, visible=True), [self.ada])

    def test_the_level_of_the_container(self):
        todolist = ops.create_list(
            project=self.project, title="Plans", creator=self.ada
        )
        set_level_override(self.bob, NotificationLevel.CONCERNS_ME, item=todolist)
        self.assertEqual(
            set(everybody(self.project, todolist, visible=False)), {self.ada}
        )
        # The same as posting into it
        todo = ops.create_todo(todolist=todolist, title="One", creator=self.ada)
        self.assertEqual(everybody(self.project, todo, visible=False), [self.ada])


class WhoCanSeeTest(TestCase):
    def test_the_same_as_visible_to(self):
        """``who_can_see()`` restates ``Item.objects.visible_to()`` for
        everybody at once: both agree for every kind of person, project,
        switch and status"""
        ada = person("Ada")  # staff, member of both
        bob = person("Bob")  # staff, member of none
        cleo = person("Cleo", client=True)  # client, member of both
        dan = person("Dan", client=True)  # client, member of none
        eve = person("Eve", is_active=False)  # inactive staff, member
        fay = person("Fay", client=True, is_active=False)  # inactive client
        own = organization("Example Team", is_own=True)
        gus = person("Gus", organization=own)  # own staff, member of none
        pia = external("Pia")  # an external, member of both
        pat = external("Pat")  # an external, member of none
        people = [ada, bob, cleo, dan, eve, fay, gus, pia, pat]
        items = []
        for all_access in [True, False]:
            p = project(
                f"All access {all_access}",
                members=[ada, cleo, eve, fay, pia],
                all_access=all_access,
            )
            for visible in [True, False]:
                todolist = ops.create_list(
                    project=p, title="List", creator=ada, visible=visible
                )
                todo = ops.create_todo(todolist=todolist, title="To-do", creator=ada)
                trashed = ops.create_todo(todolist=todolist, title="Gone", creator=ada)
                ops.trash(trashed, actor=ada)
                items += [todolist, todo, trashed]
        for item in Item.objects.filter(pk__in=[i.pk for i in items]):
            with self.subTest(item=item, project=item.project):
                self.assertEqual(
                    set(who_can_see(item)),
                    {user for user in people if can_see(user, item)},
                )


class QueriesTest(TestCase):
    """notify() and checking again when sending don't grow with the people
    told or the items of a digest"""

    def queries(self, run):
        with CaptureQueriesContext(connection) as queries:
            run()
        return len(queries)

    def test_notify(self):
        ada = person("Ada")
        p = project(members=[ada])
        todolist = ops.create_list(project=p, title="List", creator=ada)
        todo = ops.create_todo(todolist=todolist, title="To-do", creator=ada)
        counts = []
        for count in [2, 8]:
            for n in range(count):
                user = person(f"P{count}x{n}")
                subscribe(user, todo)
                if n % 2:
                    user.notification_level = NotificationLevel.CONCERNS_ME
                    user.save()
                    set_level_override(
                        user, NotificationLevel.EVERYTHING, item=todolist
                    )
            ops.add_comment(todo, author=ada, content="Hi")
            event = Event.objects.latest("pk")
            counts.append(self.queries(lambda event=event: notify(event.pk)))
            self.assertEqual(
                Notification.objects.filter(event=event).count(),
                Subscription.objects.filter(item=todo).exclude(user=ada).count(),
            )
            Subscription.objects.filter(item=todo).exclude(user=ada).delete()
        self.assertEqual(counts[0], counts[1])

    def test_deliverable(self):
        ada, bob = person("Ada"), person("Bob")
        p = project(members=[ada, bob])
        counts = []
        for count in [2, 8]:
            todolist = ops.create_list(project=p, title="List", creator=ada)
            todos = [
                ops.create_todo(todolist=todolist, title=f"T{n}", creator=ada)
                for n in range(count)
            ]
            # A level changed since doesn't hold the mail back (subscribing
            # is the switch), a hidden item does
            set_level_override(bob, NotificationLevel.CONCERNS_ME, item=todolist)
            ops.trash(todos[0], actor=ada)
            events = [
                record(actor=ada, action=Action.EDITED, project=p, item=todo)
                for todo in todos
            ]
            notifications = [Notification(user=bob, event=event) for event in events]
            counts.append(self.queries(lambda n=notifications: _deliverable(n, bob)))
            self.assertEqual(len(_deliverable(notifications, bob)), count - 1)
        self.assertEqual(counts[0], counts[1])


class OnlyListsHaveLevelsMigrationTest(TestCase):
    def test_overrides_of_other_items_go(self):
        """specs/notifications.md, "Subscriptions": projects' and lists' stay"""
        from importlib import import_module

        from django.apps import apps

        migration = import_module(
            "biwak.activity.migrations.0015_only_lists_have_levels"
        )
        ada = person("Ada")
        p = project(members=[ada])
        todolist = ops.create_list(project=p, title="List", creator=ada)
        todo = ops.create_todo(todolist=todolist, title="To-do", creator=ada)
        message = ops.create_message(project=p, title="News", creator=ada)
        for item in [todolist, todo, message]:
            LevelOverride.objects.create(user=ada, item=item, level="concerns_me")
        LevelOverride.objects.create(user=ada, project=p, level="concerns_me")
        migration.forward(apps, None)
        self.assertEqual(
            set(LevelOverride.objects.values_list("item", "project")),
            {(todolist.pk, None), (None, p.pk)},
        )
