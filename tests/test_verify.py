import unittest

from scripts.verify_claims import aggregate, build_messages, parse_verdict


class ParseVerdictTest(unittest.TestCase):
    def test_exact_labels(self):
        self.assertEqual(parse_verdict("SUPPORTS"), "SUPPORTS")
        self.assertEqual(parse_verdict("REFUTES"), "REFUTES")
        self.assertEqual(parse_verdict("NOT ENOUGH INFO"), "NOT ENOUGH INFO")

    def test_case_and_space_tolerant(self):
        self.assertEqual(parse_verdict("  supports\n"), "SUPPORTS")
        self.assertEqual(parse_verdict("Verdict: refutes"), "REFUTES")
        self.assertEqual(parse_verdict("Not Enough Info"), "NOT ENOUGH INFO")

    def test_garbage_defaults_to_nei(self):
        self.assertEqual(parse_verdict("maybe, unclear"), "NOT ENOUGH INFO")
        self.assertEqual(parse_verdict(""), "NOT ENOUGH INFO")


class AggregateTest(unittest.TestCase):
    def test_all_supports(self):
        self.assertEqual(aggregate(["SUPPORTS", "SUPPORTS"]), "SUPPORTS")

    def test_any_refutes(self):
        self.assertEqual(
            aggregate(["SUPPORTS", "REFUTES", "NOT ENOUGH INFO"]), "REFUTES")

    def test_otherwise_nei(self):
        self.assertEqual(aggregate(["SUPPORTS", "NOT ENOUGH INFO"]),
                         "NOT ENOUGH INFO")
        self.assertEqual(aggregate(["NOT ENOUGH INFO"]), "NOT ENOUGH INFO")
        self.assertEqual(aggregate([]), "NOT ENOUGH INFO")


class PromptTest(unittest.TestCase):
    def test_prompt_carries_fact_and_triples_only(self):
        fact = "Stadium Arcadium won grammies"
        triples = ["Stadium Arcadium | award received | Grammy Award"]
        messages = build_messages(fact, triples)
        text = " ".join(m["content"] for m in messages)
        self.assertIn(fact, text)
        for triple in triples:
            self.assertIn(triple, text)
        self.assertIn("ONLY", text)

    def test_prompt_handles_empty_evidence(self):
        messages = build_messages("Some fact", [])
        text = " ".join(m["content"] for m in messages)
        self.assertIn("Some fact", text)
        self.assertIn("NOT ENOUGH INFO", text)


if __name__ == "__main__":
    unittest.main()
