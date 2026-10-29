import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.fetch_evidence as fe
from scripts.fetch_evidence import _content_words, rank_triples


class RelevanceTest(unittest.TestCase):
    def test_most_relevant_triple_first(self):
        fact = "Stadium Arcadium won grammies"
        items = [
            ("performer", "Red Hot Chili Peppers",
             "S | performer | Red Hot Chili Peppers"),
            ("record label", "Warner Bros. Records",
             "S | record label | Warner Bros. Records"),
            ("award received", "Grammy Award for Best Rock Album",
             "S | award received | Grammy Award for Best Rock Album"),
        ]
        ranked = rank_triples(fact, items)
        self.assertTrue(ranked[0].startswith("S | award received |"))

    def test_stopwords_ignored(self):
        words = _content_words("Matteo Renzi served as President of Italy")
        self.assertNotIn("of", words)
        self.assertNotIn("as", words)
        self.assertIn("president", words)
        self.assertIn("italy", words)

    def test_ties_keep_original_order_and_keep_five(self):
        items = [(f"prop{i}", f"value{i}", f"S | prop{i} | value{i}")
                 for i in range(7)]
        ranked = rank_triples("qqq zzz www", items)
        self.assertEqual(ranked, [t for _, _, t in items[:5]])


class CacheTest(unittest.TestCase):
    def test_labels_for_reuses_past_answers(self):
        fe._label_cache.clear()
        try:
            calls = []

            def fake_ask(params):
                calls.append(params["ids"])
                return {"entities": {
                    q: {"labels": {"en": {"value": f"Label-{q}"}}}
                    for q in params["ids"].split("|")
                }}

            with patch.object(fe, "ask", side_effect=fake_ask):
                self.assertEqual(fe.labels_for({"Q1"}), {"Q1": "Label-Q1"})
                self.assertEqual(fe.labels_for({"Q1", "Q2"}),
                                 {"Q1": "Label-Q1", "Q2": "Label-Q2"})
            self.assertEqual(calls, ["Q1", "Q2"])
        finally:
            fe._label_cache.clear()


class OrderTest(unittest.TestCase):
    def test_main_writes_input_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_in = Path(tmp) / "in.jsonl"
            tmp_out = Path(tmp) / "out.jsonl"
            with open(tmp_in, "w") as f:
                for i in range(6):
                    f.write(json.dumps({"claim_id": i, "claim": f"c{i}",
                                        "label": "S", "atomic_claims": [f"f{i}"]}) + "\n")

            def fake_evidence(fact):
                time.sleep((5 - int(fact[1:])) * 0.05)  # early rows finish last
                return [f"ev-{fact}"]

            with patch.object(fe, "INPUT", tmp_in), \
                 patch.object(fe, "OUTPUT", tmp_out), \
                 patch.object(fe, "MAX_WORKERS", 6), \
                 patch.object(fe, "evidence_for", side_effect=fake_evidence):
                fe.main()
            out = [json.loads(line) for line in open(tmp_out)]
        self.assertEqual([r["claim_id"] for r in out], list(range(6)))
        self.assertEqual(out[0]["evidence"], [["ev-f0"]])


if __name__ == "__main__":
    unittest.main()
