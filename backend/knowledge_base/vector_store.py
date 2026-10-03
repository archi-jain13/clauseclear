import json
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np

from backend.config import KNOWLEDGE_BASE_DIR, CHROMA_PERSIST_DIR

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    TfidfVectorizer = None
    cosine_similarity = None


class StandardClauseStore:
    """
    Vector Knowledge Base storing standard/baseline legal clauses.
    Supports ChromaDB with SentenceTransformers, and robust Scikit-learn TF-IDF semantic fallback.
    """

    def __init__(self):
        self.clauses_file = KNOWLEDGE_BASE_DIR / "standard_clauses.json"
        self.standard_clauses: List[Dict[str, Any]] = []
        self.chroma_client = None
        self.collection = None
        self.embedding_model = None
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

    def initialize_store(self):
        """Initializes ChromaDB or fallback search index."""
        # Initialize fallback TF-IDF vectorizer first for guaranteed instant readiness
        if TfidfVectorizer:
            corpus_texts = [
                f"{c['category']} {c['title']} {c['baseline_text']} {' '.join(c.get('typical_red_flags', []))}"
                for c in self.standard_clauses
            ]
            self.tfidf_vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
            self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(corpus_texts)

        # Attempt ChromaDB initialization if available
        if chromadb:
            try:
                os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
                self.chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
                self.collection = self.chroma_client.get_or_create_collection(
                    name="standard_legal_clauses",
                    metadata={"hnsw:space": "cosine"}
                )
                
                # Check if collection is empty, populate it
                if self.collection.count() == 0:
                    self._populate_chroma()
            except Exception as e:
                # Fallback gracefully
                self.chroma_client = None
                self.collection = None

    def _populate_chroma(self):
        """Populates Chroma collection with standard clauses."""
        if not self.collection or not self.standard_clauses:
            return

        documents = []
        metadatas = []
        ids = []

        for c in self.standard_clauses:
            doc_text = f"Category: {c['category']}\nTitle: {c['title']}\nStandard Clause: {c['baseline_text']}\nAcceptable Range: {c.get('standard_acceptable_range', '')}"
            documents.append(doc_text)
            metadatas.append({
                "category": c["category"],
                "title": c["title"],
                "acceptable_range": c.get("standard_acceptable_range", ""),
                "raw_json": json.dumps(c)
            })
            ids.append(c["id"])

        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

    def retrieve_top_k(self, query_text: str, k: int = 2, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves the top-k most relevant baseline standard clauses for comparison.
        """
        if not self.standard_clauses:
            return []

        # 1. If Chroma collection is ready and queryable
        if self.collection and self.collection.count() > 0:
            try:
                where_clause = {"category": category} if category else None
                results = self.collection.query(
                    query_texts=[query_text],
                    n_results=min(k, len(self.standard_clauses)),
                    where=where_clause
                )
                
                matched = []
                if results and "metadatas" in results and len(results["metadatas"]) > 0:
                    for idx, meta in enumerate(results["metadatas"][0]):
                        raw_c = json.loads(meta["raw_json"])
                        score = 1.0 - (results["distances"][0][idx] if "distances" in results else 0.0)
                        raw_c["similarity_score"] = round(float(score), 3)
                        matched.append(raw_c)
                    if matched:
                        return matched
            except Exception:
                pass

        # 2. Fallback: Fast TF-IDF / Keyword Cosine Similarity
        if self.tfidf_vectorizer and self.tfidf_matrix is not None:
            query_vec = self.tfidf_vectorizer.transform([query_text])
            similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
            
            # Filter by category if requested
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

        # 3. Simple category/keyword fallback
        filtered = [c for c in self.standard_clauses if not category or c["category"] == category]
        return filtered[:k]

    def get_all_clauses(self) -> List[Dict[str, Any]]:
        """Returns all standard clauses in the knowledge base."""
        return self.standard_clauses


# Singleton instance
_store_instance: Optional[StandardClauseStore] = None

def get_clause_store() -> StandardClauseStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = StandardClauseStore()
    return _store_instance
