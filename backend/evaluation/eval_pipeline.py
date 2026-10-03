import json
import time
from pathlib import Path
from typing import Dict, Any, List

from backend.config import EVALUATION_DIR
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
    res = run_evaluation_benchmark(provider="local")
    print(format_eval_summary(res))
