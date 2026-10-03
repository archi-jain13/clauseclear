import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class ExtractedClause(BaseModel):
    clause_id: str
    clause_number: str
    clause_title: str
    clause_text: str
    raw_text: str
    start_char: int
    end_char: int
    word_count: int


# Common legal section heading patterns
HEADING_PATTERNS = [
    # E.g. "Section 1. Security Deposit", "SECTION 4 - LATE FEES", "Section 3:"
    r"(?m)^(?:SECTION|Section)\s+([0-9A-Za-z\.\-]+)[\s\:\-\–\.]+(.*)$",
    # E.g. "ARTICLE IV. MAINTENANCE", "Article 2:"
    r"(?m)^(?:ARTICLE|Article)\s+([IVXLCDM0-9\.\-]+)[\s\:\-\–\.]+(.*)$",
    # E.g. "CLAUSE 3. RENT", "Clause 4.1:"
    r"(?m)^(?:CLAUSE|Clause)\s+([0-9A-Za-z\.\-]+)[\s\:\-\–\.]+(.*)$",
    # E.g. "1. SECURITY DEPOSIT.", "1.1 Maintenance and Repairs:"
    r"(?m)^([0-9]{1,2}(?:\.[0-9]{1,2}){0,2})[\.\:\)\s\-]+([A-Z][A-Za-z0-9\s,\/\-\'\(\)]+)(?:\:|\.|\n|$)",
    # E.g. "(a) Security Deposit", "(1) Late Charges"
    r"(?m)^\(([a-z0-9]{1,2})\)[\s\:\-\.]*([A-Z][A-Za-z0-9\s,\/\-\'\(\)]+)(?:\:|\.|\n|$)",
]

# All-caps headings on their own line
ALL_CAPS_HEADING_PATTERN = r"(?m)^([A-Z0-9\s\/\-\,\&]{4,50})$"


def detect_clause_boundaries(text: str) -> List[Dict[str, Any]]:
    """
    Finds starting points, clause numbers, and clause titles across the document.
    """
    markers = []
    seen_positions = set()

    for pattern in HEADING_PATTERNS:
        for match in re.finditer(pattern, text):
            pos = match.start()
            if pos in seen_positions:
                continue
            
            groups = match.groups()
            num = groups[0].strip().rstrip(".:") if len(groups) > 0 and groups[0] else ""
            title = groups[1].strip() if len(groups) > 1 and groups[1] else ""
            
            # Clean title
            title = re.sub(r"[\:\.\-\–]+$", "", title).strip()
            if not title and num:
                title = f"Section {num}"
                
            markers.append({
                "pos": pos,
                "end_header": match.end(),
                "number": num,
                "title": title or f"Clause {len(markers)+1}",
                "matched_text": match.group(0)
            })
            seen_positions.add(pos)

    # Sort markers by appearance in text
    markers.sort(key=lambda m: m["pos"])
    
    # Filter out markers that are too close to each other (less than 10 chars)
    filtered_markers = []
    last_pos = -100
    for m in markers:
        if m["pos"] - last_pos >= 15:
            filtered_markers.append(m)
            last_pos = m["pos"]

    return filtered_markers


def chunk_by_heuristic_paragraphs(text: str) -> List[ExtractedClause]:
    """
    Fallback chunker for unnumbered or informal legal documents.
    Splits by paragraph breaks with minimal word count requirements.
    """
    paragraphs = re.split(r"\n\s*\n+", text)
    clauses = []
    current_char = 0
    clause_idx = 1

    for p in paragraphs:
        p_clean = p.strip()
        p_len = len(p_clean)
        
        if p_len < 20:  # Skip tiny fragments
            current_char += len(p) + 2
            continue

        # Look for leading title or first sentence as title
        first_line = p_clean.split("\n")[0].strip()
        if len(first_line) < 60 and (":" in first_line or first_line.isupper() or re.match(r"^[A-Z][a-zA-Z\s]+$", first_line)):
            title = first_line.strip(":#- ")
            body = "\n".join(p_clean.split("\n")[1:]).strip()
            if not body:
                body = p_clean
        else:
            # First few words as title
            words = p_clean.split()
            title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
            body = p_clean

        clauses.append(ExtractedClause(
            clause_id=f"clause-{clause_idx}",
            clause_number=f"{clause_idx}",
            clause_title=title,
            clause_text=body if body else p_clean,
            raw_text=p_clean,
            start_char=current_char,
            end_char=current_char + p_len,
            word_count=len(p_clean.split())
        ))
        clause_idx += 1
        current_char += len(p) + 2

    return clauses


def chunk_legal_document(text: str) -> List[ExtractedClause]:
    """
    Main entry point for chunking a legal contract.
    Tries structured heading detection first; falls back to paragraph segmentation if insufficient.
    """
    if not text or not text.strip():
        return []

    markers = detect_clause_boundaries(text)

    # If document has at least 3 detected clause headers, use boundary slicing
    if len(markers) >= 3:
        clauses = []
        for i, m in enumerate(markers):
            start_pos = m["pos"]
            end_pos = markers[i + 1]["pos"] if (i + 1 < len(markers)) else len(text)
            
            clause_content = text[start_pos:end_pos].strip()
            words = clause_content.split()
            
            # Extract header and body
            lines = clause_content.split("\n", 1)
            header_line = lines[0].strip()
            body_text = lines[1].strip() if len(lines) > 1 else header_line

            title = m["title"]
            if not title or title.lower().startswith("section") or title.lower().startswith("clause"):
                # Try to derive title from first line
                title_clean = re.sub(r"^(?:Section|Clause|Article|\d+[\.\)])\s*", "", header_line, flags=re.IGNORECASE)
                title = title_clean.strip(":. -") or m["title"]

            clauses.append(ExtractedClause(
                clause_id=f"clause-{i+1}",
                clause_number=m["number"] or f"{i+1}",
                clause_title=title[:80],
                clause_text=clause_content,
                raw_text=clause_content,
                start_char=start_pos,
                end_char=end_pos,
                word_count=len(words)
            ))
        return clauses

    # Fallback to paragraph chunking
    return chunk_by_heuristic_paragraphs(text)
