import unittest

from app.parsers.hevy import parse_description
from app.render import chunk_markdown, to_telegram_html

SAMPLE = """Push Day

1. Bench Press (Barbell)
Set 1: 60 kg x 10
Set 2: 80kg × 5

2. Dips
Set 1: 12 reps

3. Overhead Press
Set 1: 100 lbs x 8
"""


class Parser(unittest.TestCase):
    def test_parses_title_exercises_sets(self):
        title, sets = parse_description(SAMPLE)
        self.assertEqual(title, "Push Day")
        self.assertEqual([x.exercise for x in sets],
                         ["Bench Press (Barbell)"] * 2 + ["Dips", "Overhead Press"])
        self.assertEqual(sets[1].weight_kg, 80)
        self.assertEqual(sets[2].weight_kg, 0)          # bodyweight
        self.assertAlmostEqual(sets[3].weight_kg, 45.36, places=2)  # lbs -> kg

    def test_empty_and_garbage(self):
        self.assertEqual(parse_description(None), ("", []))
        self.assertEqual(parse_description("just some text\nmore text")[1], [])


class Render(unittest.TestCase):
    def test_escapes_html_injection(self):
        out = to_telegram_html("<script>alert(1)</script> **bold**")
        self.assertNotIn("<script>", out)
        self.assertIn("<b>bold</b>", out)

    def test_chunks_stay_under_limit(self):
        text = "\n\n".join(["word " * 200] * 20)
        chunks = chunk_markdown(text, limit=3500)
        self.assertTrue(all(len(c) <= 3500 for c in chunks))
        self.assertGreater(len(chunks), 1)

    def test_unbalanced_markdown_never_emits_unbalanced_tags(self):
        out = to_telegram_html("**unclosed bold")
        self.assertEqual(out.count("<b>"), out.count("</b>"))


if __name__ == "__main__":
    unittest.main()
