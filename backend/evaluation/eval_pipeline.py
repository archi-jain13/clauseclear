import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import DATA_DIR, EVALUATION_DIR
from backend.ingestion.chunker import ExtractedClause
from backend.analyzer.comparator import analyze_clause
from backend.analyzer.validator import run_validation_pass


def run_evaluation_benchmark(provider: str = "local") -> Dict[str, Any]:
    """
    Executes the ClauseClear evaluation pipeline across the gold labeled test set.
    Calculates Precision, Recall, F1 Score, Risk Level Accuracy, and Category Classification Accuracy.
    """
    testset_file = EVALUATION_DIR / "labeled_testset.json"
    if not testset_file.exists():
        raise FileNotFoundError(f"Testset not found: {testset_file}")

    with open(testset_file, "r", encoding="utf-8") as f:
        test_samples = json.load(f)

    start_time = time.time()
    
    tp = 0  # True Positives (Unusual correctly identified as Unusual)
    fp = 0  # False Positives (Standard falsely identified as Unusual)
    tn = 0  # True Negatives (Standard correctly identified as Standard)
    fn = 0  # False Negatives (Unusual falsely identified as Standard)

    risk_matches = 0
    category_matches = 0
    stage2_checks = 0
    stage2_corrections = 0

    detailed_results = []

    for idx, sample in enumerate(test_samples):
        # Create ExtractedClause representation
        clause_obj = ExtractedClause(
            clause_id=sample["id"],
            clause_number=f"Clause {idx+1}",
            clause_title=sample["clause_title"],
            clause_text=sample["clause_text"],
            raw_text=sample["clause_text"],
            start_char=0,
            end_char=len(sample["clause_text"]),
            word_count=len(sample["clause_text"].split())
        )

        # Stage 1: Comparison & Classification
        analyzed = analyze_clause(clause_obj, provider=provider)
        
        # Stage 2: Anti-Hallucination / Self-Consistency Validation Pass
        validated = run_validation_pass(analyzed, provider=provider)

        gt_unusual = sample["ground_truth_unusual"]
        pred_unusual = validated.is_unusual
        
        gt_risk = sample["ground_truth_risk_level"].lower()
        pred_risk = validated.risk_level.lower()

        gt_cat = sample["ground_truth_category"].lower()
        pred_cat = validated.clause_type.lower()

        # Binary confusion metrics
        if gt_unusual and pred_unusual:
            tp += 1
            classification_outcome = "TP"
        elif not gt_unusual and pred_unusual:
            fp += 1
            classification_outcome = "FP"
        elif not gt_unusual and not pred_unusual:
            tn += 1
            classification_outcome = "TN"
        else:
            fn += 1
            classification_outcome = "FN"

        # Risk level match
        is_risk_match = (gt_risk == pred_risk)
        if is_risk_match:
            risk_matches += 1

        # Category match
        is_cat_match = (gt_cat == pred_cat)
        if is_cat_match:
            category_matches += 1

        # Validation pass tracking
        if validated.validation_audit.is_validated:
            stage2_checks += 1
            if validated.validation_audit.is_false_positive:
                stage2_corrections += 1

        detailed_results.append({
            "id": sample["id"],
            "title": sample["clause_title"],
            "ground_truth_unusual": gt_unusual,
            "pred_unusual": pred_unusual,
            "ground_truth_risk": gt_risk,
            "pred_risk": pred_risk,
            "ground_truth_category": gt_cat,
            "pred_category": pred_cat,
            "classification": classification_outcome,
            "risk_match": is_risk_match,
            "category_match": is_cat_match,
            "risk_score": validated.risk_score,
            "explanation": validated.plain_language_explanation,
            "suggested_question": validated.suggested_question_to_ask_landlord,
            "validation_audit": validated.validation_audit.model_dump()
        })

    elapsed_time = round(time.time() - start_time, 3)
    total_samples = len(test_samples)

    # Calculate metrics
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1_score = round(2 * (precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    accuracy = round((tp + tn) / total_samples, 4) if total_samples > 0 else 0.0
    risk_accuracy = round(risk_matches / total_samples, 4) if total_samples > 0 else 0.0
    category_accuracy = round(category_matches / total_samples, 4) if total_samples > 0 else 0.0

    return {
        "dataset_name": "ClauseClear Legal Benchmark v1.0",
        "total_test_samples": total_samples,
        "elapsed_seconds": elapsed_time,
        "provider": provider,
        "metrics": {
            "unusual_clause_detection": {
                "precision": precision,
                "recall": recall,
                "f1_score": f1_score,
                "accuracy": accuracy,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn
            },
            "risk_level_accuracy": risk_accuracy,
            "category_classification_accuracy": category_accuracy,
            "stage2_validation": {
                "high_risk_checks_run": stage2_checks,
                "false_positives_corrected": stage2_corrections
            }
        },
        "detailed_results": detailed_results
    }


MERGED_DATA_PATH = DATA_DIR / "clauses_merged.jsonl"
# ingest_datasets drops ids already seen in the test split from train/validation, so these rows are unseen elsewhere.
HOLDOUT_ID_PREFIX = "claudette-test-"
DEFAULT_HOLDOUT_SIZE = 500
UNUSUAL_RISK_LEVELS = ("medium", "high")


def load_claudette_holdout(path: Path, sample_size: int, seed: int) -> List[Dict[str, Any]]:
    """Returns a seeded random sample of labeled CLAUDETTE test-split clauses from the merged dataset."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m backend.data.ingest_datasets` to create it."
        )
    pool = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if (
                record.get("source") == "claudette"
                and str(record.get("id", "")).startswith(HOLDOUT_ID_PREFIX)
                and record.get("risk_level") in ("low", "medium", "high")
            ):
                pool.append(record)
    if not pool:
        raise ValueError(f"No labeled CLAUDETTE test-split records found in {path}.")
    pool.sort(key=lambda r: r["id"])
    return random.Random(seed).sample(pool, min(sample_size, len(pool)))


def _binary_metrics(tp: int, fp: int, tn: int, fn: int) -> Dict[str, Any]:
    total = tp + fp + tn + fn
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def run_claudette_holdout_benchmark(
    provider: str = "local",
    sample_size: int = DEFAULT_HOLDOUT_SIZE,
    seed: int = 13,
    data_path: Path = MERGED_DATA_PATH,
) -> Dict[str, Any]:
    """
    Evaluates unusual-clause detection on a held-out CLAUDETTE sample.
    Ground truth: medium and high unfairness count as unusual, clearly fair as standard.
    """
    samples = load_claudette_holdout(data_path, sample_size, seed)
    start_time = time.time()

    tp = fp = tn = fn = risk_matches = 0
    by_truth: Dict[str, Counter] = {level: Counter() for level in ("low", "medium", "high")}
    false_positives: List[Dict[str, Any]] = []
    false_negatives: List[Dict[str, Any]] = []

    for sample in samples:
        text = sample["text"]
        clause = ExtractedClause(
            clause_id=sample["id"],
            clause_number="1",
            clause_title="Terms of Service clause",
            clause_text=text,
            raw_text=text,
            start_char=0,
            end_char=len(text),
            word_count=len(text.split()),
        )
        validated = run_validation_pass(analyze_clause(clause, provider=provider), provider=provider)

        gt_risk = sample["risk_level"]
        gt_unusual = gt_risk in UNUSUAL_RISK_LEVELS
        pred_unusual = bool(validated.is_unusual)

        by_truth[gt_risk]["total"] += 1
        by_truth[gt_risk]["predicted_unusual"] += int(pred_unusual)
        risk_matches += int(validated.risk_level.lower() == gt_risk)

        if gt_unusual and pred_unusual:
            tp += 1
        elif not gt_unusual and pred_unusual:
            fp += 1
            if len(false_positives) < 5:
                false_positives.append({"id": sample["id"], "text": text[:200], "pred_risk": validated.risk_level})
        elif not gt_unusual and not pred_unusual:
            tn += 1
        else:
            fn += 1
            if len(false_negatives) < 5:
                false_negatives.append({"id": sample["id"], "text": text[:200], "truth": gt_risk})

    total = len(samples)
    return {
        "dataset_name": "CLAUDETTE-ToS held-out test split (CodeHima/TOS_Dataset)",
        "total_test_samples": total,
        "label_distribution": {level: by_truth[level]["total"] for level in by_truth},
        "provider": provider,
        "seed": seed,
        "elapsed_seconds": round(time.time() - start_time, 3),
        "metrics": {
            "unusual_clause_detection": _binary_metrics(tp, fp, tn, fn),
            "risk_level_accuracy": round(risk_matches / total, 4) if total else 0.0,
            "flagged_unusual_by_true_label": {
                level: {"total": c["total"], "flagged": c["predicted_unusual"]} for level, c in by_truth.items()
            },
        },
        "sample_false_positives": false_positives,
        "sample_false_negatives": false_negatives,
    }


def run_combined_benchmark(
    provider: str = "local",
    include_claudette: bool = False,
    holdout_size: int = DEFAULT_HOLDOUT_SIZE,
    seed: int = 13,
    data_path: Path = MERGED_DATA_PATH,
) -> Dict[str, Any]:
    """Runs the hand-labeled benchmark and, optionally, the CLAUDETTE holdout; results are kept separate."""
    return {
        "hand_labeled": run_evaluation_benchmark(provider=provider),
        "claudette_holdout": (
            run_claudette_holdout_benchmark(provider, holdout_size, seed, data_path) if include_claudette else None
        ),
    }


def format_combined_summary(combined: Dict[str, Any]) -> str:
    """Formats both benchmarks side by side so neither number hides the other."""
    hand = combined["hand_labeled"]
    holdout = combined["claudette_holdout"]
    hm = hand["metrics"]["unusual_clause_detection"]

    lines = [format_eval_summary(hand)]
    if holdout is None:
        return lines[0]

    cm = holdout["metrics"]["unusual_clause_detection"]
    dist = holdout["label_distribution"]
    flagged = holdout["metrics"]["flagged_unusual_by_true_label"]

    def pct(value: float) -> str:
        return f"{value * 100:.1f}%"

    lines.append(f"""
# Hand-labeled set vs CLAUDETTE holdout

| Metric | Hand-labeled set | CLAUDETTE holdout |
|---|---|---|
| Samples | {hand['total_test_samples']} | {holdout['total_test_samples']} |
| Precision | {pct(hm['precision'])} | {pct(cm['precision'])} |
| Recall | {pct(hm['recall'])} | {pct(cm['recall'])} |
| F1-Score | {pct(hm['f1_score'])} | {pct(cm['f1_score'])} |
| Accuracy | {pct(hm['accuracy'])} | {pct(cm['accuracy'])} |
| Risk-level accuracy | {pct(hand['metrics']['risk_level_accuracy'])} | {pct(holdout['metrics']['risk_level_accuracy'])} |

CLAUDETTE holdout: provider `{holdout['provider']}`, seed {holdout['seed']}, labels low/medium/high = {dist['low']}/{dist['medium']}/{dist['high']}.
Confusion matrix (TP/FP/TN/FN): {cm['tp']}/{cm['fp']}/{cm['tn']}/{cm['fn']}.
Baseline accuracy of always answering "standard": {pct(dist['low'] / holdout['total_test_samples'])} (compare with Accuracy above).
Flagged unusual by true label: low {flagged['low']['flagged']}/{flagged['low']['total']}, medium {flagged['medium']['flagged']}/{flagged['medium']['total']}, high {flagged['high']['flagged']}/{flagged['high']['total']}.

CLAUDETTE sentences come from online terms of service, while the rules and baselines target leases and loans, so treat the two columns as different domains.
""")
    return "\n".join(lines)


def format_eval_summary(eval_res: Dict[str, Any]) -> str:
    """Formats evaluation results into a clean markdown table."""
    m = eval_res["metrics"]["unusual_clause_detection"]
    
    summary = f"""# ClauseClear Evaluation Benchmark Report

- **Test Set Size**: {eval_res['total_test_samples']} annotated clauses
- **Provider Tested**: `{eval_res['provider']}`
- **Execution Time**: {eval_res['elapsed_seconds']}s

## Core Performance Metrics

| Metric | Score | Formula / Notes |
|---|---|---|
| **Precision** | **{m['precision'] * 100:.1f}%** | TP / (TP + FP) — Minimizes false alarms |
| **Recall** | **{m['recall'] * 100:.1f}%** | TP / (TP + FN) — Catches predatory clauses |
| **F1-Score** | **{m['f1_score'] * 100:.1f}%** | Harmonic mean of Precision & Recall |
| **Overall Accuracy** | **{m['accuracy'] * 100:.1f}%** | (TP + TN) / Total |
| **Risk Level Accuracy** | **{eval_res['metrics']['risk_level_accuracy'] * 100:.1f}%** | Exact match on Low/Medium/High |
| **Domain Category Accuracy** | **{eval_res['metrics']['category_classification_accuracy'] * 100:.1f}%** | Match on 10+ legal domains |

## Confusion Matrix (Unusual Clause Detection)

| | Actual Unusual | Actual Standard |
|---|---|---|
| **Predicted Unusual** | **{m['tp']} (True Positive)** | {m['fp']} (False Positive) |
| **Predicted Standard** | {m['fn']} (False Negative) | **{m['tn']} (True Negative)** |

## Stage 2 Self-Consistency Verification
- **High Risk Clauses Audited**: {eval_res['metrics']['stage2_validation']['high_risk_checks_run']}
- **False Positives Corrected**: {eval_res['metrics']['stage2_validation']['false_positives_corrected']}
"""
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the ClauseClear evaluation suite.")
    parser.add_argument("--provider", default="local", help="Analysis provider; 'local' makes no cloud calls.")
    parser.add_argument("--claudette-holdout", action="store_true",
                        help="Also evaluate a held-out CLAUDETTE sample from clauses_merged.jsonl.")
    parser.add_argument("--holdout-size", type=int, default=DEFAULT_HOLDOUT_SIZE, help="Clauses sampled for the holdout.")
    parser.add_argument("--seed", type=int, default=13, help="Seed for holdout sampling.")
    parser.add_argument("--data-file", type=Path, default=MERGED_DATA_PATH, help="Merged dataset JSONL.")
    args = parser.parse_args()

    combined = run_combined_benchmark(
        provider=args.provider,
        include_claudette=args.claudette_holdout,
        holdout_size=args.holdout_size,
        seed=args.seed,
        data_path=args.data_file,
    )
    print(format_combined_summary(combined))
