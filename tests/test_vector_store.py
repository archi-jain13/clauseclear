import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import backend.knowledge_base.vector_store as vs

try:
    import lancedb  # noqa: F401
    HAS_LANCEDB = True
except ImportError:
    HAS_LANCEDB = False


def fake_embed(texts, batch_size=64):
    """Deterministic bag-of-words embedding so tests need no model download."""
    vectors = np.zeros((len(texts), vs.EMBEDDING_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().split():
            slot = int(hashlib.md5(word.encode()).hexdigest(), 16) % vs.EMBEDDING_DIM
            vectors[row, slot] += 1.0
        norm = np.linalg.norm(vectors[row])
        if norm:
            vectors[row] /= norm
    return vectors


@unittest.skipUnless(HAS_LANCEDB, "lancedb is not installed")
class TestLanceDBStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(vs, "LANCEDB_DIR", Path(self.tmp.name)),
            patch.object(vs, "embed_texts", fake_embed),
            patch.object(vs, "embedding_available", lambda: True),
        ]
        for p in self.patches:
            p.start()
        self.store = vs.StandardClauseStore()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.store.table = None
        self.tmp.cleanup()

    def test_curated_rows_are_synced_once(self):
        self.assertIsNotNone(self.store.table)
        self.assertEqual(self.store.table.count_rows(), len(self.store.standard_clauses))
        reopened = vs.StandardClauseStore()
        self.assertEqual(reopened.table.count_rows(), len(self.store.standard_clauses))

    def test_result_shape_matches_pipeline_expectations(self):
        result = self.store.retrieve_top_k("landlord may enter the premises without notice", k=1)[0]
        for key in ("id", "category", "title", "baseline_text", "standard_acceptable_range",
                    "typical_red_flags", "similarity_score"):
            self.assertIn(key, result)
        self.assertIsInstance(result["similarity_score"], float)

    def test_default_search_returns_only_curated_baselines(self):
        self.store.table.add([{
            "id": "cuad-test", "text": "landlord may enter the premises without notice",
            "category": "entry_access", "risk_level": "unlabeled", "source": "cuad",
            "vector": fake_embed(["landlord may enter the premises without notice"])[0].tolist(),
        }])
        curated_ids = {c["id"] for c in self.store.standard_clauses}
        default = self.store.retrieve_top_k("landlord may enter the premises without notice", k=3)
        self.assertTrue(all(r["id"] in curated_ids for r in default))

        everything = self.store.retrieve_top_k("landlord may enter the premises without notice", k=1, source=None)
        self.assertEqual(everything[0]["id"], "cuad-test")
        self.assertEqual(everything[0]["source"], "cuad")
        self.assertIn("baseline_text", everything[0])

    def test_category_filter(self):
        results = self.store.retrieve_top_k("late fee", k=5, category="late_fees_and_penalties")
        self.assertTrue(results)
        self.assertTrue(all(r["category"] == "late_fees_and_penalties" for r in results))

    def test_quote_in_filter_value_is_escaped(self):
        self.assertEqual(self.store.retrieve_top_k("late fee", k=1, category="x' OR '1'='1"), [])

    def add_dataset_row(self, row_id, text, source, risk):
        self.store.table.add([{
            "id": row_id, "text": text, "category": "other", "risk_level": risk, "source": source,
            "vector": fake_embed([text])[0].tolist(),
        }])

    def test_evidence_never_returns_holdout_rows(self):
        text = "we may terminate your account at any time without notice"
        self.add_dataset_row("claudette-train-1", text + " train", "claudette", "high")
        self.add_dataset_row("claudette-test-1", text, "claudette", "high")
        evidence = self.store.retrieve_evidence(text, k_labeled=5, k_reference=1)
        ids = [e["id"] for e in evidence["labeled"]]
        self.assertIn("claudette-train-1", ids)
        self.assertNotIn("claudette-test-1", ids)

    def test_evidence_splits_labeled_from_reference_and_skips_curated(self):
        text = "either party may terminate this agreement on thirty days notice"
        self.add_dataset_row("claudette-train-2", text, "claudette", "low")
        self.add_dataset_row("cuad-1", text, "cuad", "unlabeled")
        evidence = self.store.retrieve_evidence(text, k_labeled=5, k_reference=5)
        self.assertEqual({e["source"] for e in evidence["labeled"]}, {"claudette"})
        self.assertEqual({e["source"] for e in evidence["reference"]}, {"cuad"})
        self.assertEqual(evidence["labeled"][0]["risk_level"], "low")

    def test_evidence_exclude_ids_and_quote_safety(self):
        text = "you waive all rights to a class action"
        self.add_dataset_row("claudette-train-3", text, "claudette", "high")
        found = self.store.retrieve_evidence(text, k_labeled=3, k_reference=0)
        self.assertEqual(found["labeled"][0]["id"], "claudette-train-3")
        skipped = self.store.retrieve_evidence(text, k_labeled=3, k_reference=0, exclude_ids=["claudette-train-3"])
        self.assertNotIn("claudette-train-3", [e["id"] for e in skipped["labeled"]])
        self.store.retrieve_evidence(text, exclude_ids=["x' OR '1'='1"])


class TestEvidenceWithoutIndex(unittest.TestCase):

    def test_returns_empty_when_index_unavailable(self):
        with patch.object(vs, "lancedb", None):
            store = vs.StandardClauseStore()
        self.assertEqual(store.retrieve_evidence("anything"), {"labeled": [], "reference": []})


class TestTfidfFallback(unittest.TestCase):

    def test_works_without_lancedb(self):
        with patch.object(vs, "lancedb", None):
            store = vs.StandardClauseStore()
        self.assertIsNone(store.table)
        result = store.retrieve_top_k("security deposit refund timeline", k=1)
        self.assertEqual(len(result), 1)
        self.assertIn("baseline_text", result[0])
        self.assertEqual(store.retrieve_top_k("anything", k=1, source="cuad"), [])


if __name__ == "__main__":
    unittest.main()
