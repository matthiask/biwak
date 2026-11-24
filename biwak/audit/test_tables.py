"""What the audit log covers (specs/auditing.md)"""

from django.test import TestCase

from biwak.audit.models import LoggedAction
from biwak.items.models import MessageCategory


class TablesTest(TestCase):
    def test_message_categories(self):
        """Renaming or deleting one leaves a trace (decided 2026-11-24)"""
        LoggedAction.objects.all().delete()
        category = MessageCategory.objects.create(name="News", emoji="📣")
        category.name = "Updates"
        category.save()
        category.delete()
        changes = LoggedAction.objects.filter(table_name="items_messagecategory")
        self.assertEqual([c.action for c in changes], ["I", "U", "D"])
        self.assertEqual(changes[1].changed_fields, {"name": "Updates"})
