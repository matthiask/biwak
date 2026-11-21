"""The test runner: Django's, with fresh copies of the test database for the
processes of a parallel run also with ``--keepdb``"""

from django.db import connections
from django.test.runner import DiscoverRunner


class TestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        # With --keepdb Django keeps the copies of the last parallel run, which
        # miss the migrations added since: the database itself is migrated,
        # the copies aren't. Copying takes a fraction of a second.
        if self.keepdb and self.parallel > 1:
            for alias in kwargs.get("aliases") or connections:
                creation = connections[alias].creation
                # The copies' names as get_test_db_clone_settings() makes them
                # from the test database's (not yet set up here)
                test_name = creation._get_test_db_name()
                with creation._nodb_cursor() as cursor:
                    for index in range(self.parallel):
                        cursor.execute(
                            "DROP DATABASE IF EXISTS {}".format(
                                creation._quote_name(f"{test_name}_{index + 1}")
                            )
                        )
        return super().setup_databases(**kwargs)
