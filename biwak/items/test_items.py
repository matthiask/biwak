from django.core.exceptions import ValidationError
from django.test import TestCase

from biwak.activity.models import Action, Event, Subscription
from biwak.activity.operations import subscribe, unsubscribe
from biwak.items import operations as ops, visibility
from biwak.items.models import Comment, Item, Kind, Status
from biwak.test_utils import person, project


def titles(items):
    return [i.title for i in items]


class TreeTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])

    def test_allowed_parents(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada
        )
        ops.create_folder(
            project=self.project, title="Old", creator=self.ada, parent=folder
        )
        ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, parent=folder
        )
        for kind, parent in [
            (Kind.TODO, None),
            (Kind.TODO, folder),
            (Kind.LIST, todolist),
            (Kind.FOLDER, todolist),
            (Kind.MESSAGE, folder),
            (Kind.DOC, todolist),
        ]:
            with (
                self.subTest(kind=kind, parent=parent),
                self.assertRaises(ValidationError),
            ):
                Item(
                    project=self.project,
                    kind=kind,
                    parent=parent,
                    title="x",
                    creator=self.ada,
                ).save()

    def test_parent_in_other_project(self):
        other = project("Other")
        todolist = ops.create_list(project=other, title="Launch", creator=self.ada)
        with self.assertRaises(ValidationError):
            Item(
                project=self.project,
                kind=Kind.TODO,
                parent=todolist,
                title="x",
                creator=self.ada,
            ).save()

    def test_detail_rows_and_events(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        todo = ops.create_todo(todolist=todolist, title="DNS", creator=self.ada)
        self.assertEqual(todolist.detail.item, todolist)
        self.assertEqual(todo.detail.item, todo)
        self.assertEqual(
            list(Event.objects.values_list("action", "data__title")),
            [(Action.CREATED, "DNS"), (Action.CREATED, "Launch")],
        )
        self.assertTrue(Subscription.objects.filter(user=self.ada, item=todo).exists())

    def test_no_comments_on_lists(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        with self.assertRaises(ValidationError):
            ops.add_comment(todolist, author=self.ada, content="Hi")
        self.assertEqual(Comment.objects.count(), 0)

    def test_trash_and_restore_subtree(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada
        )
        sub = ops.create_folder(
            project=self.project, title="Old", creator=self.ada, parent=folder
        )
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, parent=sub
        )
        ops.trash(folder, actor=self.ada)
        self.assertEqual(
            set(Item.objects.filter(status=Status.TRASHED)), {folder, sub, doc}
        )
        self.assertNotIn(doc, Item.objects.visible_to(self.ada))
        ops.restore(folder, actor=self.ada)
        self.assertEqual(Item.objects.filter(status=Status.TRASHED).count(), 0)

    def test_restore_keeps_earlier_trashed(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada
        )
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, parent=folder
        )
        ops.trash(doc, actor=self.ada)
        ops.trash(folder, actor=self.ada)
        ops.restore(folder, actor=self.ada)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Status.TRASHED)


class OrderingTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        self.todolist = self.list.todolist
        self.high = ops.create_group(todolist=self.todolist, title="High")
        self.low = ops.create_group(todolist=self.todolist, title="Low")
        self.todos = {
            title: ops.create_todo(
                todolist=self.list, title=title, creator=self.ada, group=group
            )
            for title, group in [
                ("a", None),
                ("b", None),
                ("h1", self.high),
                ("h2", self.high),
                ("l1", self.low),
            ]
        }

    def order(self, group):
        return titles(ops._todos_in(self.list, group))

    def test_initial_order(self):
        self.assertEqual(self.order(None), ["a", "b"])
        self.assertEqual(self.order(self.high), ["h1", "h2"])

    def test_move_within_group(self):
        ops.move_todo(
            self.todos["h2"],
            todolist=self.list,
            group=self.high,
            index=0,
            actor=self.ada,
        )
        self.assertEqual(self.order(self.high), ["h2", "h1"])

    def test_move_across_heading(self):
        ops.move_todo(
            self.todos["a"], todolist=self.list, group=self.low, index=0, actor=self.ada
        )
        self.assertEqual(self.order(None), ["b"])
        self.assertEqual(self.order(self.low), ["a", "l1"])
        self.assertEqual(self.todos["b"].__class__.objects.get(title="b").position, 1)

    def test_move_group_as_block(self):
        ops.move_group(self.low, index=0)
        self.assertEqual(titles(self.todolist.groups.all()), ["Low", "High"])
        self.assertEqual(self.order(self.high), ["h1", "h2"])

    def test_delete_group_keeps_todos(self):
        ops.delete_group(self.high)
        self.assertEqual(self.order(None), ["a", "b", "h1", "h2"])

    def test_move_to_other_list(self):
        other = ops.create_list(project=self.project, title="Later", creator=self.ada)
        ops.move_todo(self.todos["a"], todolist=other, actor=self.ada)
        self.assertEqual(titles(ops._todos_in(other, None)), ["a"])
        self.assertEqual(self.order(None), ["b"])
        with self.assertRaises(ValueError):
            ops.move_todo(
                self.todos["b"], todolist=other, group=self.high, actor=self.ada
            )

    def test_complete_and_reopen(self):
        a = self.todos["a"]
        ops.complete(a, actor=self.ada)
        self.assertEqual(self.order(None), ["b"])
        a.refresh_from_db()
        self.assertEqual(a.todo.completed_by, self.ada)
        ops.reopen(a, actor=self.ada)
        self.assertEqual(self.order(None), ["b", "a"])


class VisibilityTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])

    def visible(self, user):
        return set(Item.objects.visible_to(user))

    def test_internal_by_default(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        todo = ops.create_todo(todolist=todolist, title="DNS", creator=self.ada)
        self.assertEqual(self.visible(self.ada), {todolist, todo})
        self.assertEqual(self.visible(self.cleo), set())

    def test_switch_shows_and_hides_subtree(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada
        )
        sub = ops.create_folder(
            project=self.project, title="Old", creator=self.ada, parent=folder
        )
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, parent=sub
        )
        ops.set_visibility(folder, visible=True, actor=self.ada)
        self.assertEqual(self.visible(self.cleo), {folder, sub, doc})
        # Created inside a visible folder later: visible as well
        later = ops.create_doc(
            project=self.project, title="Later", creator=self.ada, parent=sub
        )
        self.assertIn(later, self.visible(self.cleo))
        ops.set_visibility(folder, visible=False, actor=self.ada)
        self.assertEqual(self.visible(self.cleo), set())
        self.assertEqual(visibility.check(), [])

    def test_nested_items_have_no_switch(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada
        )
        sub = ops.create_folder(
            project=self.project, title="Old", creator=self.ada, parent=folder
        )
        with self.assertRaises(ValueError):
            visibility.set_switch(sub, visible=True)

    def test_moves_recompute(self):
        shared = ops.create_folder(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        internal = ops.create_folder(
            project=self.project, title="Internal", creator=self.ada
        )
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, parent=internal
        )
        ops.move_item(internal, parent=shared, actor=self.ada)
        self.assertIn(doc, self.visible(self.cleo))
        ops.move_item(internal, parent=None, actor=self.ada)
        self.assertNotIn(doc, self.visible(self.cleo))
        self.assertEqual(visibility.check(), [])

    def test_moving_todo_between_lists(self):
        shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        todo = ops.create_todo(todolist=internal, title="DNS", creator=self.ada)
        ops.move_todo(todo, todolist=shared, actor=self.ada)
        self.assertIn(todo, self.visible(self.cleo))
        self.assertEqual(visibility.check(), [])

    def test_check_finds_drift(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        todo = ops.create_todo(todolist=todolist, title="DNS", creator=self.ada)
        Item.objects.filter(pk=todo.pk).update(is_client_visible=True)
        self.assertEqual(
            [(i.pk, stored, exp) for i, stored, exp in visibility.check()],
            [(todo.pk, True, False)],
        )

    def test_affected(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        todo = ops.create_todo(todolist=todolist, title="DNS", creator=self.ada)
        ops.add_comment(todo, author=self.ada, content="Done?")
        self.assertEqual(visibility.affected(todolist), {"items": 1, "comments": 1})

    def test_assigning_clients(self):
        todolist = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        todo = ops.create_todo(todolist=todolist, title="DNS", creator=self.ada)
        with self.assertRaises(ValueError):
            ops.assign(todo, [self.cleo], actor=self.ada)
        ops.set_visibility(todolist, visible=True, actor=self.ada)
        self.assertEqual(
            ops.assign(todo, [self.cleo, self.ada], actor=self.ada),
            [self.cleo, self.ada],
        )
        self.assertEqual(ops.assign(todo, [self.cleo], actor=self.ada), [])


class SubscriptionTest(TestCase):
    def test_unsubscribing_sticks_for_automatic_subscriptions(self):
        ada, bob = person("Ada"), person("Bob")
        p = project(members=[ada, bob])
        todolist = ops.create_list(project=p, title="Launch", creator=ada)
        todo = ops.create_todo(todolist=todolist, title="DNS", creator=ada)
        ops.add_comment(todo, author=bob, content="On it")
        self.assertTrue(Subscription.objects.filter(user=bob, item=todo).exists())
        unsubscribe(bob, todo)
        ops.add_comment(todo, author=bob, content="Still on it")
        self.assertFalse(Subscription.objects.filter(user=bob, item=todo).exists())
        # Being assigned subscribes again
        ops.assign(todo, [bob], actor=ada)
        self.assertTrue(Subscription.objects.filter(user=bob, item=todo).exists())
        # Explicit subscribing too, and records who did it
        unsubscribe(bob, todo)
        subscribe(bob, todo, added_by=ada)
        self.assertEqual(Subscription.objects.get(user=bob, item=todo).added_by, ada)
