import importlib.util
import json
import logging
import threading
from typing import List, Dict, Any, Optional

import numpy as np

from backend.config import KNOWLEDGE_BASE_DIR, LANCEDB_DIR, LANCEDB_TABLE, EMBEDDING_MODEL_NAME

try:
    import lancedb
    import pyarrow as pa
except ImportError:
    lancedb = None
    pa = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    TfidfVectorizer = None
    cosine_similarity = None

logger = logging.getLogger(__name__)

# Output size of all-MiniLM-L6-v2; must match EMBEDDING_MODEL_NAME.
EMBEDDING_DIM = 384
CURATED_SOURCE = "curated"
LABELED_SOURCE = "claudette"
REFERENCE_SOURCE = "cuad"
# Rows with this id prefix are reserved for evaluation and are never returned as evidence.
HOLDOUT_ID_PREFIX = "claudette-test-"

_embedder = None
_embedder_lock = threading.Lock()


def embedding_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def _get_embedder():
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
        return _embedder


def embed_texts(texts: List[str], batch_size: int = 64) -> np.ndarray:
    """Embeds texts in batches with sentence-transformers; returns unit-length float32 vectors."""
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    vectors = _get_embedder().encode(
        texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
    )
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.shape[1] != EMBEDDING_DIM:
        raise RuntimeError(f"{EMBEDDING_MODEL_NAME} produced {vectors.shape[1]}-dim vectors, expected {EMBEDDING_DIM}.")
    return vectors


def clauses_schema():
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("category", pa.string()),
        pa.field("risk_level", pa.string()),
        pa.field("source", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    ])


def open_clauses_table():
    """Opens the embedded LanceDB `clauses` table, creating it if it does not exist."""
    if lancedb is None:
        raise RuntimeError("lancedb is not installed.")
    LANCEDB_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(LANCEDB_DIR))
    return db.create_table(LANCEDB_TABLE, schema=clauses_schema(), exist_ok=True)


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class StandardClauseStore:
    """
    Knowledge base of standard/baseline legal clauses.
    Vector search runs on an embedded LanceDB table with sentence-transformers embeddings;
    a scikit-learn TF-IDF index over the curated clauses is the fallback.
    """

    def __init__(self):
        self.clauses_file = KNOWLEDGE_BASE_DIR / "standard_clauses.json"
        self.standard_clauses: List[Dict[str, Any]] = []
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self.table = None
        self.tfidf_vectorizer = None
        self.tfidf_matrix = None

        self.load_clauses()
        self.initialize_store()

    def load_clauses(self):
        """Loads curated standard clauses from JSON."""
        if not self.clauses_file.exists():
            raise FileNotFoundError(f"Knowledge base file not found: {self.clauses_file}")

        with open(self.clauses_file, "r", encoding="utf-8") as f:
            self.standard_clauses = json.load(f)
        self._by_id = {c["id"]: c for c in self.standard_clauses}

    def initialize_store(self):
        """Builds the TF-IDF fallback, then opens LanceDB and syncs the curated rows."""
        if TfidfVectorizer:
            corpus_texts = [
                f"{c['category']} {c['title']} {c['baseline_text']} {' '.join(c.get('typical_red_flags', []))}"
                for c in self.standard_clauses
            ]
            self.tfidf_vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
            self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(corpus_texts)

        if lancedb is None or not embedding_available():
            logger.warning("LanceDB or sentence-transformers is not installed; using TF-IDF retrieval.")
            return

        try:
            table = open_clauses_table()
            self._sync_curated_rows(table)
            self.table = table
        except Exception as exc:
            logger.warning("LanceDB unavailable (%s); using TF-IDF retrieval.", exc)
            self.table = None

    def _sync_curated_rows(self, table):
        """Keeps the curated rows in LanceDB identical to standard_clauses.json."""
        existing = {
            r["id"]: r["text"]
            for r in table.search().where(f"source = {_sql_literal(CURATED_SOURCE)}")
            .select(["id", "text"]).limit(100000).to_list()
        }
        wanted = {c["id"]: c["baseline_text"] for c in self.standard_clauses}
        if existing == wanted:
            return

        if existing:
            table.delete(f"source = {_sql_literal(CURATED_SOURCE)}")
        vectors = embed_texts([c["baseline_text"] for c in self.standard_clauses])
        table.add([
            {
                "id": c["id"],
                "text": c["baseline_text"],
                "category": c["category"],
                "risk_level": "low",
                "source": CURATED_SOURCE,
                "vector": vectors[i].tolist(),
            }
            for i, c in enumerate(self.standard_clauses)
        ])

    def _row_to_result(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Converts a LanceDB row into the clause dict shape the analysis pipeline expects."""
        curated = self._by_id.get(row["id"]) if row["source"] == CURATED_SOURCE else None
        if curated is not None:
            result = dict(curated)
        else:
            result = {
                "id": row["id"],
                "category": row["category"],
                "title": f"{row['source']} clause",
                "baseline_text": row["text"],
                "standard_acceptable_range": "",
                "typical_red_flags": [],
                "risk_level": row["risk_level"],
                "source": row["source"],
            }
        result["similarity_score"] = round(1.0 - float(row["_distance"]), 3)
        return result

    def retrieve_top_k(
        self,
        query_text: str,
        k: int = 2,
        category: Optional[str] = None,
        source: Optional[str] = CURATED_SOURCE,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves the top-k most relevant clauses for comparison.
        Defaults to the curated baselines; pass source=None to search every dataset in the table.
        """
        if not self.standard_clauses:
            return []

        if self.table is not None:
            try:
                filters = []
                if source:
                    filters.append(f"source = {_sql_literal(source)}")
                if category:
                    filters.append(f"category = {_sql_literal(category)}")
                query = self.table.search(embed_texts([query_text])[0].tolist()).metric("cosine")
                if filters:
                    query = query.where(" AND ".join(filters), prefilter=True)
                rows = query.limit(k).to_list()
                if rows:
                    return [self._row_to_result(r) for r in rows]
            except Exception as exc:
                logger.warning("LanceDB query failed (%s); falling back to TF-IDF.", exc)

        if source not in (None, CURATED_SOURCE):
            return []

        if self.tfidf_vectorizer and self.tfidf_matrix is not None:
            query_vec = self.tfidf_vectorizer.transform([query_text])
            similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

            candidates = []
            for idx, c in enumerate(self.standard_clauses):
                if category and c["category"] != category:
                    continue
                score = similarities[idx]
                c_copy = dict(c)
                c_copy["similarity_score"] = round(float(score), 3)
                candidates.append((score, c_copy))

            candidates.sort(key=lambda x: x[0], reverse=True)
            return [c for _, c in candidates[:k]]

        filtered = [c for c in self.standard_clauses if not category or c["category"] == category]
        return filtered[:k]

    def retrieve_evidence(
        self,
        query_text: str,
        k_labeled: int = 5,
        k_reference: int = 2,
        exclude_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Finds the nearest labeled terms-of-service sentences (risk labels) and CUAD contract clauses
        (unlabeled reference wording). Evaluation holdout rows are always excluded.
        Returns empty lists when the vector index is unavailable.
        """
        evidence: Dict[str, List[Dict[str, Any]]] = {"labeled": [], "reference": []}
        if self.table is None:
            return evidence

        excluded = "".join(f" AND id != {_sql_literal(i)}" for i in (exclude_ids or []))
        searches = {
            "labeled": (
                k_labeled,
                f"source = {_sql_literal(LABELED_SOURCE)} AND NOT (id LIKE {_sql_literal(HOLDOUT_ID_PREFIX + '%')}){excluded}",
            ),
            "reference": (k_reference, f"source = {_sql_literal(REFERENCE_SOURCE)}{excluded}"),
        }
        try:
            vector = embed_texts([query_text])[0].tolist()
            for key, (k, where) in searches.items():
                if k <= 0:
                    continue
                rows = (
                    self.table.search(vector).metric("cosine").where(where, prefilter=True).limit(k).to_list()
                )
                evidence[key] = [
                    {
                        "id": r["id"],
                        "text": r["text"],
                        "category": r["category"],
                        "risk_level": r["risk_level"],
                        "source": r["source"],
                        "similarity": round(1.0 - float(r["_distance"]), 3),
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("Evidence retrieval failed (%s); continuing without it.", exc)
            return {"labeled": [], "reference": []}
        return evidence

    def get_all_clauses(self) -> List[Dict[str, Any]]:
        """Returns all curated standard clauses."""
        return self.standard_clauses


# Singleton instance
_store_instance: Optional[StandardClauseStore] = None

def get_clause_store() -> StandardClauseStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = StandardClauseStore()
    return _store_instance
