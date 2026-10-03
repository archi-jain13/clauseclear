import json
import tempfile
import unittest
from pathlib import Path

from backend.data import ingest_datasets as ing
from backend.evaluation import eval_pipeline as ev


def cuad_row(category, answers):
    return {
        "question": f'Highlight the parts (if any) of this contract related to "{category}" that should be reviewed by a lawyer.',
        "answers": {"text": answers, "answer_start": [0] * len(answers)},
    }


LONG = "Either party may terminate this Agreement for convenience upon thirty days written notice."


class TestCuadIngest(unittest.TestCase):

    def test_category_regex(self):
        self.assertEqual(ing.extract_cuad_category(cuad_row("Governing Law", [])["question"]), "Governing Law")
        self.assertIsNone(ing.extract_cuad_category("no category here"))

    def test_maps_relevant_and_drops_irrelevant(self):
        rows = [
            cuad_row("Termination For Convenience", [LONG]),
            cuad_row("Non-Compete", [LONG + " Non-compete."]),
            cuad_row("Ip Ownership Assignment", [LONG + " IP."]),
        ]
        records, stats = ing.build_cuad_records(rows, None, 1)
        self.assertEqual([r["category"] for r in records], ["termination_notice"])
        self.assertEqual(records[0]["risk_level"], "unlabeled")
        self.assertEqual(records[0]["raw_label"], "Termination For Convenience")
        self.assertEqual(stats["dropped_irrelevant_category"], 2)

    def test_dedupes_and_skips_short_or_empty_answers(self):
        rows = [cuad_row("Insurance", [LONG, LONG, "Yes", "  "]), cuad_row("Insurance", [LONG])]
        records, stats = ing.build_cuad_records(rows, None, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(stats["dropped_duplicate"], 2)
        self.assertEqual(stats["dropped_empty_or_short"], 2)

    def test_every_mapped_category_is_an_app_category(self):
        self.assertTrue(set(ing.CUAD_TO_APP_CATEGORY.values()) <= set(ing.APP_CATEGORIES))

    def test_limit_samples_rows(self):
        rows = [cuad_row("Insurance", [f"{LONG} Variant number {i}."]) for i in range(50)]
        records, stats = ing.build_cuad_records(rows, 10, 1)
        self.assertEqual(stats["rows_scanned"], 10)
        self.assertEqual(len(records), 10)


class TestClaudetteIngest(unittest.TestCase):

    def test_label_mapping_and_unique_ids(self):
        splits = {
            "train": [
                {"sentence": "Clearly fair sentence one.", "unfairness_level": "clearly_fair"},
                {"sentence": "A potentially unfair sentence.", "unfairness_level": "potentially_unfair"},
            ],
            "test": [{"sentence": "A clearly unfair sentence.", "unfairness_level": "clearly_unfair"}],
        }
        records, _ = ing.build_claudette_records(splits, None, 1)
        by_label = {r["raw_label"]: r["risk_level"] for r in records}
        self.assertEqual(by_label, {"clearly_fair": "low", "potentially_unfair": "medium", "clearly_unfair": "high"})
        self.assertEqual(len({r["id"] for r in records}), len(records))
        self.assertTrue(all(r["category"] == "other" and r["source"] == "claudette" for r in records))

    def test_duplicates_are_dropped_from_train_not_test(self):
        sentence = "Same sentence appearing in two splits."
        splits = {
            "train": [{"sentence": sentence, "unfairness_level": "clearly_fair"}],
            "test": [{"sentence": sentence, "unfairness_level": "clearly_unfair"}],
        }
        records, stats = ing.build_claudette_records(splits, None, 1)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["id"].startswith("claudette-test-"))
        self.assertEqual(stats["duplicate_label_conflicts"], 1)


class TestHoldoutEvaluation(unittest.TestCase):

    def write_dataset(self, directory):
        path = Path(directory) / "merged.jsonl"
        rows = [
            {"id": "claudette-test-0", "source": "claudette", "category": "other", "risk_level": "low", "text": "Fine text.", "raw_label": "clearly_fair"},
            {"id": "claudette-test-1", "source": "claudette", "category": "other", "risk_level": "high", "text": "Unfair text.", "raw_label": "clearly_unfair"},
            {"id": "claudette-train-2", "source": "claudette", "category": "other", "risk_level": "high", "text": "Train row.", "raw_label": "clearly_unfair"},
            {"id": "cuad-abc", "source": "cuad", "category": "insurance", "risk_level": "unlabeled", "text": "Insurance text.", "raw_label": "Insurance"},
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return path

    def test_holdout_uses_only_labeled_claudette_test_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = ev.load_claudette_holdout(self.write_dataset(tmp), 10, 1)
        self.assertEqual({r["id"] for r in sample}, {"claudette-test-0", "claudette-test-1"})

    def test_missing_dataset_has_helpful_error(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            ev.load_claudette_holdout(Path("does-not-exist.jsonl"), 10, 1)
        self.assertIn("ingest_datasets", str(ctx.exception))

    def test_binary_metrics(self):
        m = ev._binary_metrics(tp=3, fp=1, tn=5, fn=1)
        self.assertEqual(m["precision"], 0.75)
        self.assertEqual(m["recall"], 0.75)
        self.assertEqual(m["accuracy"], 0.8)
        self.assertEqual(ev._binary_metrics(0, 0, 4, 0)["f1_score"], 0.0)

    def test_holdout_benchmark_reports_separate_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ev.run_claudette_holdout_benchmark("local", 10, 1, self.write_dataset(tmp))
        self.assertEqual(result["total_test_samples"], 2)
        self.assertEqual(result["label_distribution"], {"low": 1, "medium": 0, "high": 1})
        metrics = result["metrics"]["unusual_clause_detection"]
        self.assertEqual(metrics["tp"] + metrics["fp"] + metrics["tn"] + metrics["fn"], 2)


if __name__ == "__main__":
    unittest.main()
