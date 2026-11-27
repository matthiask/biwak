"""The test runner: Django's, with fresh copies of the test database for the
processes of a parallel run also with ``--keepdb``, and the same CSRF token
on every page"""

from django.db import connections
from django.middleware import csrf
from django.test.runner import DiscoverRunner, ParallelTestSuite


def fixed_csrf_tokens(*args):
    """A random token contains words now and then ("Now", "ago"), which
    failed tests asserting a word isn't on the page. Secret and mask are
    the same string of zeros: the tokens still pass the checks of
    ``Client(enforce_csrf_checks=True)``"""
    csrf._get_new_csrf_string = lambda: "0" * csrf.CSRF_SECRET_LENGTH


class FixedCsrfParallelTestSuite(ParallelTestSuite):
    # Runs in every process of a parallel run (forkserver: nothing patched
    # in this one reaches them)
    process_setup = fixed_csrf_tokens


class TestRunner(DiscoverRunner):
    parallel_test_suite = FixedCsrfParallelTestSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        fixed_csrf_tokens()

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
