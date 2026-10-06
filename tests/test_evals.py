import unittest

from evals.run_evals import evaluate


class Good:
    def complete(self, system, messages, max_tokens=700):
        return "Nice work. **Z2 dominated.** New PR on the bench - keep it going."


class Hallucinating:
    def complete(self, system, messages, max_tokens=700):
        return "You ran 99 km and your e1RM is 250 kg."


class EvalHarness(unittest.TestCase):
    def test_good_model_scores_perfect(self):
        r = evaluate(Good(), samples=2)
        self.assertEqual(r["summary"]["grounded"], 1.0)
        self.assertEqual(r["n"], 10)

    def test_hallucinating_model_fails_gate(self):
        r = evaluate(Hallucinating(), samples=1)
        self.assertEqual(r["summary"]["grounded"], 0.0)
        self.assertIn("99", r["rows"][0]["ungrounded"])


if __name__ == "__main__":
    unittest.main()
