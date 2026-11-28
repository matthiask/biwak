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


class UserNameTest(TestCase):
    def test_names_beyond_ascii(self):
        """PostgreSQL keeps only ASCII in ``application_name``: the name is
        written without accents instead of as escapes"""
        from biwak.accounts.middleware import set_user_name
        from biwak.test_utils import person

        jurg = person("Jürg Müller")
        set_user_name(jurg)
        LoggedAction.objects.all().delete()
        MessageCategory.objects.create(name="News", emoji="📣")
        (change,) = LoggedAction.objects.filter(table_name="items_messagecategory")
        self.assertEqual(change.user_name, f"user-{jurg.pk}-Jurg")


class SignInTablesTest(TestCase):
    def test_addresses_and_linked_accounts(self):
        """Who linked a Google account or changed a sign-in address
        (decided 2026-11-28); the profile allauth writes at every sign-in
        isn't a change"""
        from allauth.account.models import EmailAddress
        from allauth.socialaccount.models import SocialAccount

        from biwak.test_utils import person

        ada = person("Ada")
        LoggedAction.objects.all().delete()
        EmailAddress.objects.create(user=ada, email="ada.e@example.org")
        account = SocialAccount.objects.create(
            user=ada, provider="google", uid="1", extra_data={"name": "Ada"}
        )
        account.extra_data = {"name": "Ada E."}
        account.save()
        account.delete()
        self.assertEqual(
            [
                (c.table_name, c.action)
                for c in LoggedAction.objects.filter(
                    table_name__in=[
                        "account_emailaddress",
                        "socialaccount_socialaccount",
                    ]
                ).order_by("event_id")
            ],
            [
                ("account_emailaddress", "I"),
                ("socialaccount_socialaccount", "I"),
                ("socialaccount_socialaccount", "D"),
            ],
        )


class CommandNameTest(TestCase):
    def test_commands_name_themselves(self):
        """What a command run by hand or a migration changes is logged under
        its name (decided 2026-11-28; jobs that set a name keep theirs)"""
        import os
        import subprocess
        import sys
        from pathlib import Path

        from django.conf import settings
        from django.db import connection

        db = connection.settings_dict
        url = "postgres://{}:{}@{}:{}/{}".format(
            db["USER"], db["PASSWORD"], db["HOST"], db["PORT"] or 5432, db["NAME"]
        )
        code = (
            "from django.db import connection\n"
            "with connection.cursor() as c:\n"
            "    c.execute(\"SELECT current_setting('application_name')\")\n"
            "    print(c.fetchone()[0])\n"
        )
        result = subprocess.run(
            [sys.executable, "manage.py", "shell", "-c", code],
            cwd=Path(settings.BASE_DIR),
            env={k: v for k, v in os.environ.items() if k != "PGAPPNAME"}
            | {"DATABASE_URL": url, "TESTING": "True", "SECRET_KEY": "testing"},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.splitlines()[-1], "manage.py shell")
