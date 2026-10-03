"""Embeds clauses_merged.jsonl and loads it into the LanceDB `clauses` table.

Run from the project root (after ingest_datasets):  python -m backend.data.seed_lancedb
Re-running replaces the rows for the sources found in the file and leaves other sources (e.g. curated) alone.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import DATA_DIR, LANCEDB_DIR
from backend.knowledge_base.vector_store import (
    CURATED_SOURCE,
    EMBEDDING_DIM,
    _sql_literal,
    embed_texts,
    open_clauses_table,
)

INPUT_PATH = DATA_DIR / "clauses_merged.jsonl"
REQUIRED_FIELDS = ("id", "source", "category", "risk_level", "text")
PROGRESS_EVERY = 500


def read_records(path: Path) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    seen = set()
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            missing = [f for f in REQUIRED_FIELDS if not record.get(f)]
            if missing:
                raise ValueError(f"{path.name}:{line_number} is missing {', '.join(missing)}")
            if record["id"] in seen:
                raise ValueError(f"{path.name}:{line_number} repeats id {record['id']}")
            seen.add(record["id"])
            records.append(record)
    return records


def batched(items: List[Dict[str, str]], size: int) -> Iterator[List[Dict[str, str]]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def seed(path: Path, batch_size: int = PROGRESS_EVERY) -> int:
    records = read_records(path)
    if not records:
        print(f"No records found in {path}.")
        return 0
    if any(r["source"] == CURATED_SOURCE for r in records):
        raise ValueError(f"The '{CURATED_SOURCE}' source is managed by the app and cannot be seeded from a file.")

    table = open_clauses_table()
    sources = sorted({r["source"] for r in records})
    print(f"Replacing existing rows for sources: {', '.join(sources)}")
    table.delete("source IN (" + ", ".join(_sql_literal(s) for s in sources) + ")")

    print(f"Embedding and inserting {len(records)} records into {LANCEDB_DIR} (batch size {batch_size}) ...")
    started = time.time()
    inserted = 0
    for batch in batched(records, batch_size):
        vectors = embed_texts([r["text"] for r in batch])
        if vectors.shape != (len(batch), EMBEDDING_DIM):
            raise RuntimeError(f"Unexpected embedding shape {vectors.shape}")
        table.add([
            {
                "id": r["id"],
                "text": r["text"],
                "category": r["category"],
                "risk_level": r["risk_level"],
                "source": r["source"],
                "vector": vectors[i].tolist(),
            }
            for i, r in enumerate(batch)
        ])
        inserted += len(batch)
        if inserted % PROGRESS_EVERY == 0 or inserted == len(records):
            print(f"  {inserted}/{len(records)} records ({time.time() - started:.0f}s)")

    print(f"Done. Table now holds {table.count_rows()} rows.")
    return inserted


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=INPUT_PATH, help="Merged JSONL file to load.")
    parser.add_argument("--batch-size", type=int, default=PROGRESS_EVERY,
                        help="Records embedded and inserted per batch (progress prints every 500 records).")
    args = parser.parse_args(argv)
    if args.batch_size <= 0:
        parser.error("--batch-size must be a positive integer.")
    if not args.input.exists():
        parser.error(f"{args.input} not found. Run python -m backend.data.ingest_datasets first.")
    seed(args.input, args.batch_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
