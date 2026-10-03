"""Fetches CUAD and CLAUDETTE-ToS from Hugging Face and merges them into clauses_merged.jsonl.

Run from the project root:  python -m backend.data.ingest_datasets --limit 2000
"""
import argparse
import collections
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import DATA_DIR

OUTPUT_PATH = DATA_DIR / "clauses_merged.jsonl"

CUAD_DATASET = "theatticusproject/cuad-qa"
# cuad-qa ships a loading script that datasets>=4 refuses to run; the auto-converted parquet branch has the same rows.
CUAD_PARQUET_REVISION = "refs/convert/parquet"
TOS_DATASET = "CodeHima/TOS_Dataset"

CUAD_CATEGORY_RE = re.compile(r'related to "([^"]+)"')
MIN_CLAUSE_CHARS = 30

APP_CATEGORIES = [
    "security_deposit", "termination_notice", "maintenance_repairs", "indemnification",
    "late_fees_penalties", "renewal", "entry_access", "dispute_resolution",
    "assignment_subletting", "liability_cap", "insurance", "governing_law", "other",
]

# CUAD categories that map onto lease/loan concerns. Every other CUAD category (Non-Compete,
# IP Ownership, Change Of Control, License Grant, Parties, dates, ...) is dropped, not sent to "other".
CUAD_TO_APP_CATEGORY = {
    "Termination For Convenience": "termination_notice",
    "Renewal Term": "renewal",
    "Notice Period To Terminate Renewal": "renewal",
    "Anti-Assignment": "assignment_subletting",
    "Cap On Liability": "liability_cap",
    "Uncapped Liability": "liability_cap",
    "Liquidated Damages": "late_fees_penalties",
    "Insurance": "insurance",
    "Governing Law": "governing_law",
    "Covenant Not To Sue": "dispute_resolution",
}

RISK_BY_UNFAIRNESS = {
    "clearly_fair": "low",
    "potentially_unfair": "medium",
    "clearly_unfair": "high",
}

# Test first so that duplicates across splits are dropped from train, keeping the held-out split clean.
TOS_SPLIT_ORDER = ("test", "validation", "train")


def clean_text(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def dedupe_key(*parts: str) -> str:
    return hashlib.sha1("|".join(p.lower() for p in parts).encode("utf-8")).hexdigest()


def extract_cuad_category(question: str) -> Optional[str]:
    match = CUAD_CATEGORY_RE.search(question or "")
    return match.group(1) if match else None


def sample_rows(rows: Sequence[Any], limit: Optional[int], seed: int) -> Iterable[Tuple[int, Any]]:
    """Yields (position, row) for up to `limit` rows in original order, sampled at random so a small limit is not one contract."""
    if limit is None or limit >= len(rows):
        for position, row in enumerate(rows):
            yield position, row
        return
    for position in sorted(random.Random(seed).sample(range(len(rows)), limit)):
        yield position, rows[position]


def build_cuad_records(rows: Sequence[Dict[str, Any]], limit: Optional[int], seed: int) -> Tuple[List[Dict[str, str]], collections.Counter]:
    stats: collections.Counter = collections.Counter()
    records: List[Dict[str, str]] = []
    seen = set()

    for _, row in sample_rows(rows, limit, seed):
        stats["rows_scanned"] += 1
        raw_category = extract_cuad_category(row.get("question", ""))
        if raw_category is None:
            stats["dropped_no_category"] += 1
            continue
        app_category = CUAD_TO_APP_CATEGORY.get(raw_category)
        if app_category is None:
            stats["dropped_irrelevant_category"] += 1
            continue

        for answer in (row.get("answers") or {}).get("text") or []:
            text = clean_text(answer)
            if len(text) < MIN_CLAUSE_CHARS:
                stats["dropped_empty_or_short"] += 1
                continue
            key = dedupe_key(app_category, text)
            if key in seen:
                stats["dropped_duplicate"] += 1
                continue
            seen.add(key)
            records.append({
                "id": f"cuad-{key[:12]}",
                "source": "cuad",
                "category": app_category,
                "risk_level": "unlabeled",
                "text": text,
                "raw_label": raw_category,
            })
    return records, stats


def build_claudette_records(splits: Mapping[str, Sequence[Mapping[str, Any]]], limit: Optional[int], seed: int) -> Tuple[List[Dict[str, str]], collections.Counter]:
    stats: collections.Counter = collections.Counter()
    records: List[Dict[str, str]] = []
    first_risk: Dict[str, str] = {}

    for split in TOS_SPLIT_ORDER:
        rows = splits.get(split)
        if rows is None:
            continue
        for position, row in sample_rows(rows, limit, seed):
            stats["rows_scanned"] += 1
            level = row.get("unfairness_level")
            risk = RISK_BY_UNFAIRNESS.get(level)
            if risk is None:
                stats["dropped_unknown_label"] += 1
                continue
            text = clean_text(row.get("sentence"))
            if not text:
                stats["dropped_empty_or_short"] += 1
                continue
            key = dedupe_key(text)
            if key in first_risk:
                stats["dropped_duplicate"] += 1
                if first_risk[key] != risk:
                    stats["duplicate_label_conflicts"] += 1
                continue
            first_risk[key] = risk
            records.append({
                "id": f"claudette-{split}-{position}",
                "source": "claudette",
                "category": "other",
                "risk_level": risk,
                "text": text,
                "raw_label": level,
            })
    return records, stats


def load_cuad_rows() -> Sequence[Dict[str, Any]]:
    from datasets import load_dataset
    try:
        return load_dataset(CUAD_DATASET, split="train")
    except Exception as exc:
        print(f"Direct CUAD load failed ({type(exc).__name__}); using the parquet revision.")
        return load_dataset(CUAD_DATASET, split="train", revision=CUAD_PARQUET_REVISION)


def load_tos_splits() -> Dict[str, Sequence[Dict[str, Any]]]:
    from datasets import load_dataset
    dataset = load_dataset(TOS_DATASET)
    return {name: dataset[name] for name in dataset.keys()}


def write_jsonl(records: Iterable[Dict[str, str]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def print_summary(records: List[Dict[str, str]], source_stats: Dict[str, collections.Counter], output: Path) -> None:
    print(f"\nWrote {len(records)} records to {output}")
    for source, stats in source_stats.items():
        print(f"\n[{source}] scanned {stats['rows_scanned']} input rows")
        for key in sorted(k for k in stats if k != "rows_scanned"):
            print(f"  {key}: {stats[key]}")

    by_source_category = collections.Counter((r["source"], r["category"]) for r in records)
    print("\nRecords per source / category:")
    for (source, category), count in sorted(by_source_category.items()):
        print(f"  {source:10} {category:24} {count}")

    by_source_risk = collections.Counter((r["source"], r["risk_level"]) for r in records)
    print("\nRecords per source / risk_level:")
    for (source, risk), count in sorted(by_source_risk.items()):
        print(f"  {source:10} {risk:10} {count}")

    covered = {r["category"] for r in records}
    missing = [c for c in APP_CATEGORIES if c not in covered]
    if missing:
        print("\nApp categories with no records from these datasets: " + ", ".join(missing))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None,
                        help="Randomly sample at most N input rows from CUAD, and N rows per split from ToS (CUAD has ~22k).")
    parser.add_argument("--seed", type=int, default=13, help="Seed for --limit sampling.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output JSONL path.")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer.")

    print(f"Loading {CUAD_DATASET} ...")
    cuad_records, cuad_stats = build_cuad_records(load_cuad_rows(), args.limit, args.seed)
    print(f"Loading {TOS_DATASET} ...")
    tos_records, tos_stats = build_claudette_records(load_tos_splits(), args.limit, args.seed)

    records = cuad_records + tos_records
    write_jsonl(records, args.output)
    print_summary(records, {"cuad": cuad_stats, "claudette": tos_stats}, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
