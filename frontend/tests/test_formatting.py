import unittest
from datetime import date

import formatting as f


class FormattingTests(unittest.TestCase):
    def test_nice(self):
        self.assertEqual(f.nice("NOT_STARTED"), "Not started")
        self.assertEqual(f.nice(None), "")

    def test_days_left_text(self):
        self.assertEqual(f.days_left_text(-1), "overdue by 1 day")
        self.assertEqual(f.days_left_text(-5), "overdue by 5 days")
        self.assertEqual(f.days_left_text(0), "due today")
        self.assertEqual(f.days_left_text(1), "due tomorrow")
        self.assertEqual(f.days_left_text(9), "in 9 days")

    def test_dates(self):
        self.assertEqual(f.format_date("2026-10-14"), "14 Oct 2026")
        self.assertEqual(f.format_date(None), "—")
        self.assertEqual(f.parse_date("2026-10-14"), date(2026, 10, 14))
        self.assertIsNone(f.parse_date(""))

    def test_datetime_bad_value_does_not_crash(self):
        self.assertEqual(f.format_datetime("not a date"), "not a date")
        self.assertEqual(f.format_datetime(None), "—")
        self.assertIn("Oct 2026", f.format_datetime("2026-10-14T10:30:00Z"))

    def test_money_uses_exact_decimal_strings(self):
        self.assertEqual(f.format_money("3000.00"), "₹3,000.00")
        self.assertEqual(f.format_money("1234.5"), "₹1,234.50")
        self.assertEqual(f.to_number("garbage"), 0.0)

    def test_level_label_colours_only_fixed_words(self):
        self.assertEqual(f.level_label("CRITICAL"), ":red[**Critical**]")
        self.assertEqual(f.level_label("LOW"), ":gray[**Low**]")
        self.assertEqual(f.level_label("???"), ":gray[**???**]")

    def test_short(self):
        self.assertEqual(f.short("abc", 10), "abc")
        self.assertEqual(len(f.short("x" * 500, 100)), 100)
        self.assertEqual(f.short(None), "")

    def test_choices_match_backend_enums(self):
        # copied from backend/app/models.py; if the backend changes, this test reminds you to update formatting.py
        self.assertEqual(f.ACTIVITY_TYPES, ["PROJECT", "EXAM", "TRIP", "MEETING", "APPOINTMENT", "EVENT", "PERSONAL", "CUSTOM"])
        self.assertEqual(f.ACTIVITY_STATUSES, ["NOT_STARTED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"])


if __name__ == "__main__":
    unittest.main()
