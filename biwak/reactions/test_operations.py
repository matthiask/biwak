from django.core.exceptions import ValidationError
from django.test import TestCase

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.reactions import operations
from biwak.reactions.emoji import QUICK
from biwak.reactions.models import Reaction, can_react
from biwak.test_utils import person, project


class OperationsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.project = project(members=[self.ada, self.bob])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )
        self.comment = ops.add_comment(self.todo, author=self.ada, content="Hi")

    def test_quick_set(self):
        self.assertEqual(len(QUICK), 32)
        self.assertEqual(len(set(QUICK)), 32)

    def test_toggle_on_todo(self):
        self.assertTrue(operations.toggle_reaction(self.bob, "👍", item=self.todo))
        self.assertEqual(Reaction.objects.get().content, "👍")
        event = Event.objects.get(action=Action.REACTED)
        self.assertEqual(event.actor, self.bob)
        self.assertEqual(event.data["content"], "👍")
        self.assertNotIn("comment", event.data)
        # Again: removed, and the event with it
        self.assertFalse(operations.toggle_reaction(self.bob, "👍", item=self.todo))
        self.assertFalse(Reaction.objects.exists())
        self.assertFalse(Event.objects.filter(action=Action.REACTED).exists())

    def test_toggle_on_comment(self):
        operations.toggle_reaction(self.bob, "Thanks!", comment=self.comment)
        reaction = Reaction.objects.get()
        self.assertEqual(reaction.comment, self.comment)
        self.assertEqual(reaction.item, self.todo)
        event = Event.objects.get(action=Action.REACTED)
        self.assertEqual(event.data["comment"], self.comment.pk)
        # The same text on the to-do itself is another reaction
        operations.toggle_reaction(self.bob, "Thanks!", item=self.todo)
        self.assertEqual(Reaction.objects.count(), 2)
        operations.toggle_reaction(self.bob, "Thanks!", comment=self.comment)
        self.assertEqual(
            list(Reaction.objects.values_list("comment", flat=True)), [None]
        )
        self.assertEqual(Event.objects.filter(action=Action.REACTED).count(), 1)

    def test_several_from_one_person_and_others(self):
        operations.toggle_reaction(self.bob, "👍", item=self.todo)
        operations.toggle_reaction(self.bob, "🎉", item=self.todo)
        operations.toggle_reaction(self.ada, "👍", item=self.todo)
        self.assertEqual(Reaction.objects.count(), 3)
        # Only your own is removed
        operations.toggle_reaction(self.ada, "👍", item=self.todo)
        self.assertEqual(
            sorted(Reaction.objects.values_list("user__email", "content")),
            [(self.bob.email, "🎉"), (self.bob.email, "👍")],
        )

    def test_content(self):
        for content in ["", "   ", "x" * 41]:
            with self.assertRaises(ValidationError):
                operations.toggle_reaction(self.bob, content, item=self.todo)
        operations.toggle_reaction(self.bob, "  Nice \n work ", item=self.todo)
        operations.toggle_reaction(self.bob, "x" * 40, item=self.todo)
        self.assertEqual(
            sorted(Reaction.objects.values_list("content", flat=True)),
            ["Nice work", "x" * 40],
        )
        # The same, differently spaced, removes it
        operations.toggle_reaction(self.bob, "Nice   work", item=self.todo)
        self.assertEqual(Reaction.objects.count(), 1)

    def test_only_reactable_things(self):
        with self.assertRaises(ValidationError):
            operations.toggle_reaction(self.bob, "👍", item=self.list)
        self.assertFalse(can_react(self.list))
        with self.assertRaises(ValueError):
            operations.toggle_reaction(self.bob, "👍")
        other = ops.create_todo(todolist=self.list, title="Other", creator=self.ada)
        self.assertFalse(can_react(other, self.comment))

    def test_removing_when_there_is_none(self):
        self.assertFalse(operations.remove_reaction(self.bob, "👍", item=self.todo))

    def test_idempotent_add(self):
        self.assertTrue(operations.add_reaction(self.bob, "👍", item=self.todo))
        self.assertFalse(operations.add_reaction(self.bob, "👍", item=self.todo))
        self.assertEqual(Event.objects.filter(action=Action.REACTED).count(), 1)

    def test_deleted_comment_takes_reactions(self):
        operations.toggle_reaction(self.bob, "👍", comment=self.comment)
        self.comment.delete()
        self.assertFalse(Reaction.objects.exists())

    def test_not_project_activity(self):
        before = self.project.__class__.objects.get().last_activity_at
        operations.toggle_reaction(self.bob, "👍", item=self.todo)
        self.assertEqual(self.project.__class__.objects.get().last_activity_at, before)

    def test_summary(self):
        operations.toggle_reaction(self.bob, "👍", item=self.todo)
        operations.toggle_reaction(self.ada, "👍", item=self.todo)
        operations.toggle_reaction(self.ada, "🎉", item=self.todo)
        operations.toggle_reaction(self.ada, "Nice", comment=self.comment)
        todo = Item.objects.get(pk=self.todo.pk)
        found = operations.summary(todo, None, self.bob)
        self.assertEqual(
            [(r["content"], r["count"], r["mine"]) for r in found],
            [("👍", 2, True), ("🎉", 1, False)],
        )
        self.assertEqual(found[0]["people"], [self.bob, self.ada])
        found = operations.summary(todo, self.comment, self.bob)
        self.assertEqual([r["content"] for r in found], ["Nice"])
