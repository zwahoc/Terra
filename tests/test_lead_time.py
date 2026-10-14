import unittest

from backend.app.domain.lead_time import demo_township_lead_time_days


class DemoLeadTimeTests(unittest.TestCase):
    def test_same_township(self):
        self.assertEqual(demo_township_lead_time_days('Elmina', 'Elmina'), 1)

    def test_different_townships(self):
        self.assertEqual(demo_township_lead_time_days('Elmina', 'Bukit Raja'), 2)

    def test_case_and_whitespace_are_not_different_areas(self):
        self.assertEqual(demo_township_lead_time_days(' Bukit  Raja ', 'bukit raja'), 1)

    def test_similar_names_are_not_assumed_same_area(self):
        self.assertEqual(demo_township_lead_time_days('Elmina', 'Elmina Heights'), 2)

    def test_unknown_townships_are_not_guessed(self):
        for a, b in [(None, 'Elmina'), ('Elmina', None), ('', 'Elmina'), (' ', ' '), (1, 'Elmina')]:
            with self.subTest(a=a, b=b):
                self.assertIsNone(demo_township_lead_time_days(a, b))


if __name__ == '__main__':
    unittest.main()
