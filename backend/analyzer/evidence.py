"""Turns retrieved dataset neighbours into a risk signal (local engine) and prompt context (LLMs)."""
from typing import Any, Dict, List, Optional

# Chosen on the CLAUDETTE validation split (best F1 with precision >= 0.6); the test split is never used for tuning.
VOTE_K = 5
VOTE_MIN_SIMILARITY = 0.6
VOTE_UNFAIR_SHARE = 0.5
VOTE_MIN_NEIGHBOURS = 2
MEDIUM_VOTE_SCORE = 45

PROMPT_MIN_SIMILARITY = 0.5
PROMPT_LABELED_EXAMPLES = 3
PROMPT_REFERENCE_EXAMPLES = 1
PROMPT_EXAMPLE_CHARS = 180

LABEL_NAMES = {"low": "fair", "medium": "potentially unfair", "high": "clearly unfair"}

Evidence = Dict[str, List[Dict[str, Any]]]


def neighbour_vote(evidence: Optional[Evidence]) -> Optional[Dict[str, Any]]:
    """
    Similarity-weighted vote of the nearest labeled neighbours.
    Returns None when too few neighbours are close enough to say anything.
    """
    if not evidence:
        return None
    close = [
        n for n in evidence.get("labeled", [])[:VOTE_K]
        if n["similarity"] >= VOTE_MIN_SIMILARITY and n["risk_level"] in LABEL_NAMES
    ]
    if len(close) < VOTE_MIN_NEIGHBOURS:
        return None
    total = sum(n["similarity"] for n in close)
    unfair = [n for n in close if n["risk_level"] in ("medium", "high")]
    return {
        "unfair_share": sum(n["similarity"] for n in unfair) / total,
        "used": len(close),
        "unfair_count": len(unfair),
    }


def vote_flags_unfair(vote: Optional[Dict[str, Any]]) -> bool:
    return vote is not None and vote["unfair_share"] >= VOTE_UNFAIR_SHARE


def vote_deviation_text(vote: Dict[str, Any]) -> str:
    return (
        f"Wording is close to example clauses that annotators labeled potentially or clearly unfair "
        f"({vote['unfair_count']} of the {vote['used']} nearest examples, CLAUDETTE terms-of-service data)."
    )


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PROMPT_EXAMPLE_CHARS else text[:PROMPT_EXAMPLE_CHARS].rstrip() + "..."


def format_evidence_for_prompt(evidence: Optional[Evidence]) -> str:
    """Compact context block for an LLM prompt; empty string when nothing relevant was found."""
    if not evidence:
        return ""
    labeled = [n for n in evidence.get("labeled", []) if n["similarity"] >= PROMPT_MIN_SIMILARITY][:PROMPT_LABELED_EXAMPLES]
    reference = [n for n in evidence.get("reference", []) if n["similarity"] >= PROMPT_MIN_SIMILARITY][:PROMPT_REFERENCE_EXAMPLES]
    if not labeled and not reference:
        return ""

    lines = ["Similar example clauses (context only; they come from other documents and may not apply here):"]
    for n in labeled:
        lines.append(f'- Annotators labeled this {LABEL_NAMES.get(n["risk_level"], n["risk_level"])}: "{_clip(n["text"])}"')
    for n in reference:
        label = n["category"].replace("_", " ")
        lines.append(f'- Wording used in a real commercial contract ({label}): "{_clip(n["text"])}"')
    return "\n".join(lines)
