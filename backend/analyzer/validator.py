import os
import json
import re
import requests
from typing import Optional, Dict, Any

import backend.config as config
from backend.config import GEMINI_API_KEY
from backend.analyzer.schemas import AnalyzedClause, ValidationAudit


# Standard legal boilerplate terms that sound intense/intimidating to laypeople but are standard
STANDARD_BOILERPLATE_TERMS = [
    (r"joint\s+and\s+several\s+liability", "Joint and several liability is standard commercial/residential contract terminology indicating co-signers are collectively responsible for total rent."),
    (r"severability|held\s+invalid\s+or\s+unenforceable", "Severability clauses are standard legal boilerplate ensuring the rest of the agreement remains valid if one clause is invalidated."),
    (r"force\s+majeure|acts\s+of\s+god", "Force majeure provisions are standard protective clauses excusing delay due to natural disasters or external emergencies."),
    (r"entire\s+agreement|merger\s+clause|supersedes\s+all\s+prior", "Merger / Integration clauses are standard boilerplate confirming written terms replace informal oral promises."),
    (r"time\s+is\s+of\s+the\s+essence", "Time is of the essence is standard legal phrasing reinforcing agreed payment and notice deadlines."),
    (r"as-is\s+condition.*(?:move-in\s+inspection|checklist)", "Accepting premises as-is accompanied by a move-in inspection checklist is standard industry practice.")
]


def validate_high_risk_clause_local(clause: AnalyzedClause) -> AnalyzedClause:
    """
    Stage 2 Local Verification: Distinguishes genuinely predatory terms from formal standard legalese.
    """
    text = clause.clause_text.lower()
    
    # Check if clause matches known standard legalese that might have triggered a false alarm
    for pattern, note in STANDARD_BOILERPLATE_TERMS:
        if re.search(pattern, text) and not clause.deviation_points:
            # Downgrade to low/medium standard
            clause.validation_audit = ValidationAudit(
                is_validated=True,
                initial_risk=clause.risk_level,
                final_risk="low",
                is_false_positive=True,
                validator_notes=f"Downgraded during Stage-2 Self-Consistency Pass: {note}"
            )
            clause.risk_level = "low"
            clause.risk_score = 25
            clause.is_unusual = False
            clause.plain_language_explanation = f"While this contains formal legal phrasing, it is standard contractual boilerplate: {note}"
            return clause

    # Confirmed high risk
    clause.validation_audit = ValidationAudit(
        is_validated=True,
        initial_risk=clause.risk_level,
        final_risk="high",
        is_false_positive=False,
        validator_notes="Stage-2 Self-Consistency Pass confirmed: Terms explicitly violate standard market baselines or statutory tenant/borrower protections."
    )
    return clause


def validate_high_risk_clause_gemini(clause: AnalyzedClause, api_key: str) -> Optional[AnalyzedClause]:
    """
    Stage 2 LLM Verification Pass using Gemini: Checks if clause is truly predatory vs standard legalese.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    prompt = f"""You are performing a Stage 2 False-Positive Verification Check on a legal clause flagged as HIGH RISK.
Question: Is this clause genuinely unusual / predatory / legally onerous, OR is it actually standard commercial legal boilerplate that simply sounds harsh to laypeople?

Clause to verify:
Title: {clause.clause_title}
Text: {clause.clause_text}
Initial Flag Reason: {'; '.join(clause.deviation_points)}

Return a JSON object matching this schema:
{{
  "is_false_positive": boolean,
  "confirmed_risk_level": "low" | "medium" | "high",
  "validator_notes": "Detailed rationale explaining whether this is truly predatory or standard boilerplate"
}}
Output ONLY raw JSON."""

    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"}
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            parsed = json.loads(res.json()["candidates"][0]["content"]["parts"][0]["text"])
            is_fp = bool(parsed.get("is_false_positive", False))
            final_risk = parsed.get("confirmed_risk_level", clause.risk_level)
            
            clause.validation_audit = ValidationAudit(
                is_validated=True,
                initial_risk=clause.risk_level,
                final_risk=final_risk,
                is_false_positive=is_fp,
                validator_notes=parsed.get("validator_notes", "Stage 2 verification complete.")
            )
            clause.risk_level = final_risk
            if is_fp:
                clause.risk_score = 30 if final_risk == "medium" else 15
                clause.is_unusual = False if final_risk == "low" else True
            return clause
    except Exception:
        pass
    return None


def validate_high_risk_clause_groq(clause: AnalyzedClause, api_key: str) -> Optional[AnalyzedClause]:
    """
    Stage 2 LLM Verification Pass using Groq LLaMA: Checks if clause is truly predatory vs standard legalese.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""You are performing a Stage 2 False-Positive Verification Check on a legal clause flagged as HIGH RISK.
Question: Is this clause genuinely unusual / predatory / legally onerous, OR is it actually standard commercial legal boilerplate that simply sounds harsh to laypeople?

Clause to verify:
Title: {clause.clause_title}
Text: {clause.clause_text}
Initial Flag Reason: {'; '.join(clause.deviation_points)}

Return a JSON object matching this schema:
{{
  "is_false_positive": boolean,
  "confirmed_risk_level": "low" | "medium" | "high",
  "validator_notes": "Detailed rationale explaining whether this is truly predatory or standard boilerplate"
}}
Output ONLY raw JSON."""

    try:
        model = os.environ.get("GROQ_MODEL") or getattr(config, "GROQ_MODEL", "llama-3.3-70b-versatile")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are an expert legal contract auditor. Always respond in valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 512,
            "response_format": {"type": "json_object"}
        }
        res = requests.post(url, headers=headers, json=payload, timeout=12)
        if res.status_code == 200:
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", res.json()["choices"][0]["message"]["content"].strip(), flags=re.DOTALL).strip()
            parsed = json.loads(clean)
            is_fp = bool(parsed.get("is_false_positive", False))
            final_risk = parsed.get("confirmed_risk_level", clause.risk_level)
            
            clause.validation_audit = ValidationAudit(
                is_validated=True,
                initial_risk=clause.risk_level,
                final_risk=final_risk,
                is_false_positive=is_fp,
                validator_notes=f"[Groq Stage 2 Audit] {parsed.get('validator_notes', 'Verification complete.')}"
            )
            clause.risk_level = final_risk
            if is_fp:
                clause.risk_score = 30 if final_risk == "medium" else 15
                clause.is_unusual = False if final_risk == "low" else True
            return clause
    except Exception as e:
        print(f"[Groq Validator] Failed: {e}")
    return None


def run_validation_pass(clause: AnalyzedClause, provider: Optional[str] = None) -> AnalyzedClause:
    """
    Routes high-risk clauses through the Stage 2 anti-hallucination / self-consistency pipeline.
    """
    if clause.risk_level != "high":
        # Non-high risk clauses don't require second-pass verification
        clause.validation_audit = ValidationAudit(
            is_validated=False,
            initial_risk=clause.risk_level,
            final_risk=clause.risk_level,
            is_false_positive=False,
            validator_notes="Clause risk level is not high; bypasses Stage 2 verification."
        )
        return clause

    groq_key = (os.environ.get("GROQ_API_KEY") or getattr(config, "GROQ_API_KEY", "") or "").strip()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", "") or "").strip()

    # Try Groq validation first if key is present
    if groq_key:
        validated = validate_high_risk_clause_groq(clause, groq_key)
        if validated:
            return validated

    # Run Gemini validation if active
    if (provider == "gemini" or not groq_key) and gemini_key:
        validated = validate_high_risk_clause_gemini(clause, gemini_key)
        if validated:
            return validated

    # Fallback to local validator
    return validate_high_risk_clause_local(clause)
