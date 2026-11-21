import datetime as dt

from django import forms
from django.test import SimpleTestCase, TestCase

from biwak.schedules_forms import KEEP, RuleField, RuleFormMixin, RuleWidget
from biwak.test_utils import person


class Form(RuleFormMixin, forms.Form):
    rule = RuleField(label="Repeat")


class Required(forms.Form):
    rule = RuleField(label="Asked", allow_empty=False, default_frequency="weekly")


INITIAL = {"rule": "FREQ=MONTHLY;BYMONTHDAY=1,15"}


def post(**data):
    return {f"rule_{key}": value for key, value in data.items()}


class FieldTest(SimpleTestCase):
    def test_cleans_to_the_rule(self):
        form = Form(post(frequency="weekly", interval="2", weekdays=["TU"]))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["rule"], "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU")

    def test_empty(self):
        form = Form({})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["rule"], "")
        form = Required({})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["rule"], ["Choose how often it repeats."])

    def test_errors_per_part(self):
        form = Form(post(frequency="weekly", interval="0"))
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["rule"],
            ["Enter a number from 1 to 99.", "Choose at least one weekday."],
        )

    def test_keeping_unless_replaced(self):
        form = Form(post(keep="1"), initial=INITIAL)
        self.assertTrue(form.is_valid())
        self.assertIs(form.cleaned_data["rule"], KEEP)
        # The rest is ignored while it's kept
        form = Form(post(keep="1", frequency="daily", interval="1"), initial=INITIAL)
        self.assertTrue(form.is_valid())
        self.assertIs(form.cleaned_data["rule"], KEEP)
        form = Form(
            post(keep="1", replace="1", frequency="daily", interval="1"),
            initial=INITIAL,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["rule"], "FREQ=DAILY")

    def test_keeping_needs_a_stored_rule(self):
        form = Form(post(keep="1"))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["rule"], "")
        form = Required(post(keep="1"))
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["rule"], ["Choose how often it repeats."])

    def test_a_bound_form_shows_what_was_posted(self):
        form = Form(
            post(frequency="monthly", interval="3", monthly="day", month_day="40")
        )
        html = str(form["rule"])
        self.assertIn('<option value="monthly" selected>', html)
        self.assertIn('value="40"', html)
        self.assertIn('value="3"', html)


class WidgetTest(SimpleTestCase):
    def render(self, value, **kwargs):
        return RuleWidget(**kwargs).render("rule", value, attrs={"id": "x"})

    def test_a_new_rule_starts_from_the_anchor(self):
        widget = RuleWidget(default_frequency="weekly")
        widget.anchor = dt.date(2026, 11, 20)  # a Friday
        html = widget.render("rule", None, attrs={"id": "x"})
        self.assertIn('<option value="weekly" selected>', html)
        self.assertIn('value="FR"\n              checked', html)
        self.assertIn('name="rule_month_day"', html)
        self.assertIn("every Friday", html)

    def test_checkins_always_repeat(self):
        self.assertNotIn("Doesn&#x27;t repeat", self.render("", allow_empty=False))
        self.assertIn("Doesn&#x27;t repeat", self.render(""))

    def test_the_description(self):
        html = self.render("FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1")
        self.assertIn("the last Friday of every month", html)
        self.assertRegex(html, r'<option\s+value="-1"\s+selected\s*>')
        self.assertNotIn("can't be edited here", html)

    def test_a_rule_set_elsewhere(self):
        html = self.render("FREQ=MONTHLY;BYMONTHDAY=1,15")
        self.assertIn("This schedule was set elsewhere and can't be edited here", html)
        self.assertIn('name="rule_keep"', html)
        self.assertIn('name="rule_replace"', html)

    def test_ids_come_from_the_attributes(self):
        html = self.render("")
        self.assertIn('id="x_frequency"', html)
        self.assertIn('for="x_interval"', html)


class DescribeTest(TestCase):
    def setUp(self):
        self.client.force_login(person("Ada"))

    def get(self, query):
        return self.client.get("/schedules/describe/", query)

    def test_describes(self):
        response = self.get({
            "name": "rule",
            "rule_frequency": "weekly",
            "rule_interval": "2",
            "rule_weekdays": ["MO", "TH"],
        })
        self.assertContains(response, "every 2 weeks on Monday, Thursday")

    def test_names_prefix_the_fields(self):
        response = self.get({
            "name": "recurrence",
            "recurrence_frequency": "daily",
            "recurrence_interval": "4",
        })
        self.assertContains(response, "every 4 days")

    def test_errors(self):
        response = self.get({
            "name": "rule",
            "rule_frequency": "weekly",
            "rule_interval": "1",
        })
        self.assertContains(response, "Choose at least one weekday.")
        self.assertContains(response, "text-danger")

    def test_nothing_and_leaving_a_rule_alone(self):
        self.assertEqual(self.get({"name": "rule", "rule_frequency": ""}).content, b"")
        response = self.get({
            "name": "rule",
            "rule_keep": "1",
            "rule_frequency": "daily",
            "rule_interval": "1",
        })
        self.assertEqual(response.content, b"")

    def test_a_bad_name(self):
        self.assertEqual(self.get({"name": "a b"}).status_code, 400)
        self.assertEqual(self.get({}).status_code, 400)

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/schedules/describe/", {"name": "rule"})
        self.assertEqual(response.status_code, 302)
