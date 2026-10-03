import json
import re
import os
from typing import List, Dict, Any, Optional, Tuple
import requests

import backend.config as config
from backend.config import DEFAULT_PROVIDER
from backend.ingestion.chunker import ExtractedClause
from backend.knowledge_base.vector_store import get_clause_store
from backend.analyzer.schemas import AnalyzedClause, ValidationAudit


def _get_active_groq_key() -> str:
    return (os.environ.get("GROQ_API_KEY") or getattr(config, "GROQ_API_KEY", "") or "").strip()


def _get_active_gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", "") or "").strip()


# Rule-based pattern indicators for domain classification and risk detection
CATEGORY_KEYWORDS = {
    "security_deposit": ["security deposit", "damage deposit", "deposit refund", "deductions from deposit", "escrow", "cleaning deposit", "deposit return", "deposit"],
    "termination_and_notice": ["termination", "early termination", "notice to vacate", "notice period", "cure period", "default", "eviction", "breach of agreement", "right to re-enter", "vacate"],
    "maintenance_and_repairs": ["maintenance", "repairs", "plumbing", "hvac", "air conditioning", "heating", "habitability", "wear and tear", "tenant responsibilities", "furnace", "roof"],
    "late_fees_and_penalties": ["late fee", "late charge", "grace period", "penalty", "daily fee", "overdue balance", "delinquent", "due date"],
    "entry_and_privacy": ["right of entry", "landlord access", "inspection", "advance notice", "quiet enjoyment", "showing property", "24 hours notice", "emergency access", "enter the leased premises", "24/7"],
    "subletting_and_assignment": ["sublet", "sublease", "assignment", "assign", "re-let", "subtenant", "transfer of lease", "unauthorized guest"],
    "rent_escalation_and_renewal": ["rent increase", "escalation", "renewal", "automatic renewal", "cpi", "adjusted rent", "subsequent term", "automatically renew"],
    "indemnification_and_liability": ["indemnify", "indemnification", "hold harmless", "limitation of liability", "waiver of liability", "gross negligence", "damages waiver", "joint and several"],
    "dispute_resolution_and_governing_law": ["governing law", "jurisdiction", "attorney fees", "attorneys' fees", "arbitration", "jury trial waiver", "dispute resolution", "severability", "court"],
    "utilities_and_services": ["utility", "utilities", "water", "electricity", "gas", "sewer", "trash", "internet", "cable", "metered", "sub-meter"],
    "pets_and_animals": ["pet", "pets", "dog", "cat", "animal", "pet fee", "pet deposit", "pet rent", "service animal", "emotional support"],
    "parking_and_storage": ["parking", "garage", "vehicle", "parking space", "towing", "storage", "assigned parking", "car"],
    "insurance_and_casualty": ["renters insurance", "insurance", "casualty", "fire", "loss", "liability insurance", "coverage"],
    "guests_and_occupancy": ["guest", "guests", "visitor", "occupant", "occupancy", "unauthorized resident", "extended stay"],
    "alterations_and_fixtures": ["alteration", "alterations", "paint", "painting", "fixtures", "modifications", "nails", "drill", "decorating"],
    "rent_payment": ["rent payment", "monthly rent", "payment method", "rent is due", "due on", "payment of rent", "payable"],
    "loan_interest_and_usury": ["interest rate", "apr", "annual percentage", "usury", "finance charge", "amortization", "compound interest", "promissory note", "interest"],
    "loan_prepayment_and_default": ["prepayment", "prepayment penalty", "acceleration", "accelerate maturity", "confession of judgment", "cognovit", "maturity", "cure", "prepay"]
}

# Red-flag heuristic patterns for high/medium risk detection
HIGH_RISK_PATTERNS = [
    (r"non-refundable\s+security\s+deposit|non-refundable\s+and\s+forfeited|deemed\s+non-refundable", "Security deposit explicitly declared non-refundable or forfeited immediately.", "security_deposit", 88),
    (r"(?:forfeit|forfeiture)\s+(?:of\s+)?(?:entire|the\s+full|all)\s+deposit|forfeited\s+in\s+full", "Entire deposit forfeited immediately on minor or single violation.", "security_deposit", 85),
    (r"deposit\s+(?:returned|refunded).*(?:60|90|120)\s+days", "Deposit return timeline exceeds standard 30-day statutory cap.", "security_deposit", 75),
    (r"(?:enter|access).*(?:at\s+any\s+time|without\s+(?:prior\s+)?notice|24\/7)", "Landlord claims unrestricted entry without advance notice, violating tenant right to quiet enjoyment.", "entry_and_privacy", 92),
    (r"waive[s]?\s+(?:the\s+)?right\s+to\s+(?:prior\s+)?(?:written\s+)?notice", "Waiver of advance notice before landlord entry.", "entry_and_privacy", 80),
    (r"(?:late\s+fee|penalty)\s+(?:of\s+)?(?:\$?[5-9][0-9]|\$[1-9][0-9]{2,})\s+per\s+day", "Extortionate compounding daily late fee.", "late_fees_and_penalties", 90),
    (r"late\s+fee\s+(?:of\s+)?(?:1[5-9]|[2-9][0-9])\%", "Late fee percentage exceeds standard 5-10% statutory limits.", "late_fees_and_penalties", 85),
    (r"no\s+grace\s+period", "Zero grace period before levying late penalty.", "late_fees_and_penalties", 70),
    (r"tenant\s+(?:shall|agrees\s+to)\s+(?:bear\s+full\s+financial\s+cost|replace|maintain|repair).*(?:roof|hvac|furnace|foundation|structure|main\s+plumbing)", "Shifts major structural/HVAC capital replacement costs onto tenant.", "maintenance_and_repairs", 95),
    (r"waive[s]?\s+(?:any\s+and\s+all\s+)?(?:implied\s+)?warrant(?:y|ies)\s+of\s+habitability", "Waiver of the implied warranty of habitability (legally void and severe red flag).", "maintenance_and_repairs", 98),
    (r"(?:indemnify|hold\s+harmless)\s+landlord.*(?:landlord\'?s\s+(?:own\s+)?(?:gross\s+)?negligence|sole\s+fault)", "Requires tenant to indemnify landlord even for landlord's own gross negligence.", "indemnification_and_liability", 92),
    (r"waive[s]?\s+(?:any\s+right\s+to\s+)?(?:a\s+)?jury\s+trial", "Waiver of constitutional right to jury trial in disputes.", "dispute_resolution_and_governing_law", 65),
    (r"confession\s+of\s+judgment|cognovit|confess\s+judgment", "Confession of judgment clause allows lender/landlord to obtain judgment without trial or defense.", "loan_prepayment_and_default", 99),
    (r"prepayment\s+penalty\s+(?:equal\s+to|of\s+)?(?:all\s+remaining\s+unearned\s+interest|all\s+remaining\s+interest|[1-9][0-9]\%)", "Onerous prepayment penalty charging unearned future interest upon early payoff.", "loan_prepayment_and_default", 88),
    (r"(?:immediate\s+acceleration|accelerate\s+maturity|accelerates\s+all\s+principal).*(?:without\s+notice|without\s+opportunity\s+to\s+cure)", "Immediate debt acceleration without notice or opportunity to cure.", "loan_prepayment_and_default", 90),
    (r"(?:interest\s+rate|apr|annual\s+percentage\s+rate).*?(?:[3-9][0-9]|[1-9][0-9]{2,})\%", "Interest rate exceeds statutory usury limits (>30% APR).", "loan_interest_and_usury", 95)
]

MEDIUM_RISK_PATTERNS = [
    (r"automatic(?:ally)?\s+renew.*(?:1[0-9]|2[0-9])\%|automatic(?:ally)?\s+renew.*(?:90|120)\s+days", "Automatic lease renewal with steep rent increase or lengthy 90+ day opt-out window.", "rent_escalation_and_renewal", 60),
    (r"subletting\s+is\s+strictly\s+prohibited|unauthorized\s+guest.*penalty\s+fee", "Absolute ban on subletting and severe unauthorized guest penalty.", "subletting_and_assignment", 55),
    (r"tenant\s+pays\s+all\s+attorney(?:\'s)?\s+fees|tenant\s+shall\s+pay\s+landlord\'s\s+attorney", "One-sided attorney fee clause favoring only the landlord/lender.", "dispute_resolution_and_governing_law", 58),
    (r"repair\s+deductible\s+of\s+\$[1-9][0-9]{2,}", "Mandatory high deductible on all repair service calls.", "maintenance_and_repairs", 55),
    (r"notice\s+period\s+of\s+(?:60|90|120)\s+days", "Extended notice period longer than standard 30 days.", "termination_and_notice", 45)
]


def classify_clause_category(clause_text: str, title: str = "") -> str:
    """Classifies a clause into a legal domain based on keyword frequency."""
    text_lower = f"{title.lower()} {clause_text.lower()}"
    scores = {}
    
    for category, kw_list in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in kw_list:
            if kw in text_lower:
                score += (3 if kw in title.lower() else 1)
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)
    return "general"


def generate_tailored_clause_question(
    clause_title: str,
    clause_text: str,
    category: str,
    risk_level: str,
    is_unusual: bool,
    deviations: Optional[List[str]] = None,
    default_question: str = ""
) -> str:
    """
    Constructs a sharp, dynamic, context-specific question to ask the landlord or lender.
    Guarantees no two clauses get identical generic text by contextualizing:
    1. The specific section/clause title and subject matter.
    2. Any extracted numbers, percentages, or timeframes.
    3. The exact red-flag deviation detected (for unusual/high-risk clauses).
    4. Practical, operational clarification points (for standard/low-risk clauses).
    """
    dev_list = deviations or []
    # Clean and resolve title
    title = (clause_title or "").strip()
    if not title or title.lower() in ("clause", "section", "pasted legal document", "untitled", "extracted clause"):
        words = clause_text.strip().split()
        if len(words) >= 3:
            title = " ".join(words[:4]).rstrip(":,.;-")
        else:
            title = category.replace("_", " ").title()

    title_ref = f"Section '{title}'" if not title.lower().startswith(("section", "clause", "article")) else f"'{title}'"

    # Extract specific dollar amounts or timeframes
    amounts = re.findall(r"\$[\d,]+(?:\.\d{2})?|\b\d+\s*(?:%|days?|hours?|months?)\b", clause_text, re.IGNORECASE)
    amount_str = f" ({', '.join(amounts[:2])})" if amounts else ""

    if is_unusual or risk_level in ("high", "medium"):
        if dev_list:
            dev = dev_list[0].rstrip(".")
            dev_lower = dev.lower()
            if "non-refundable" in dev_lower or "forfeit" in dev_lower:
                return f"Regarding {title_ref}{amount_str}: Since the current text states that the deposit is non-refundable or subject to forfeiture, can we amend this clause so the deposit is fully refundable within 21 days of move-out, minus only documented damages beyond normal wear and tear?"
            elif "unrestricted entry" in dev_lower or "without" in dev_lower or "24/7" in dev_lower or ("notice" in dev_lower and "entry" in category):
                return f"Regarding {title_ref}: Given that this provision allows landlord entry without advance notice, can we revise the wording to require at least 24 hours advance written notice for any routine visit, restricting unannounced entry strictly to verified life-safety emergencies?"
            elif "structural" in dev_lower or "hvac" in dev_lower or "roof" in dev_lower or "furnace" in dev_lower:
                return f"Regarding {title_ref}: This clause shifts major structural and system repairs to the tenant. Can we explicitly state in the lease that the landlord remains responsible for structural and mechanical systems (HVAC, plumbing, electrical, roof), while the tenant is only responsible for minor day-to-day upkeep?"
            elif "late fee" in dev_lower or "daily fee" in dev_lower or "compounding" in dev_lower:
                return f"Regarding {title_ref}{amount_str}: Could we adjust the late fee structure to include a standard 5-day grace period and cap the late charge at a reasonable one-time fee (such as 5% of monthly rent), eliminating daily compounding charges?"
            elif "habitability" in dev_lower:
                return f"Regarding {title_ref}: Can we remove the waiver of habitability to ensure the agreement complies with statutory implied warranty of habitability protections guaranteeing safe and habitable residential premises?"
            elif "indemnif" in dev_lower or "negligence" in dev_lower or "hold harmless" in dev_lower:
                return f"Regarding {title_ref}: Can we revise the indemnification language to be mutual and hold each party accountable only for their own direct negligence, explicitly excluding tenant liability for the landlord's own acts or omissions?"
            elif "jury" in dev_lower or "arbitration" in dev_lower or "confession" in dev_lower or "acceleration" in dev_lower:
                return f"Regarding {title_ref}: Can we replace the unilateral dispute / acceleration terms with a balanced clause providing at least a 30-day written cure notice before any legal escalation or declaration of default?"
            elif "sublet" in dev_lower or "guest" in dev_lower:
                return f"Regarding {title_ref}: Can we modify this provision to allow subletting or lease assignment with prior written landlord approval (not to be unreasonably withheld or delayed) for qualified replacement tenants?"
            elif "renew" in dev_lower or "escalat" in dev_lower:
                return f"Regarding {title_ref}{amount_str}: Can we require at least 60 days advance written notice from the landlord of any proposed rent adjustment prior to lease renewal, with any increase capped at the local inflation rate?"
            else:
                return f"Regarding {title_ref}: The clause specifies that {dev}. Can we discuss amending this provision to reflect standard commercial tenant protections and require mutual written consent before enforcement?"
        elif risk_level == "high":
            return f"Regarding {title_ref}{amount_str}: This clause contains non-standard and highly restrictive terms for the tenant. Can we discuss revising this section to adopt standard, balanced language commonly used in market rental agreements?"
        else:
            return f"Under {title_ref}{amount_str}: Could you clarify the specific conditions under which this clause would be triggered, and can we add language ensuring at least 14 days written notice prior to any enforcement action?"

    # Standard / Low-risk clause templates
    low_risk_templates = {
        "security_deposit": f"Regarding {title_ref}: Could you confirm the required timeline (e.g., 21 days) and method for returning the security deposit after move-out, and that normal wear and tear will be explicitly exempt from deductions?",
        "rent_payment": f"Under {title_ref}: What payment methods are accepted through your portal (e.g. ACH, online debit, check) and are there any added convenience fees for paying online?",
        "late_fees_and_penalties": f"Regarding {title_ref}: Could you confirm the exact grace period (e.g. 5 days) before late fees take effect, and how rent payments received on weekends or bank holidays are processed?",
        "entry_and_privacy": f"Under {title_ref}: Will I receive advance entry notifications via email or SMS, and is non-emergency entry typically scheduled during standard business hours (9 AM - 5 PM)?",
        "maintenance_and_repairs": f"Regarding {title_ref}: What is the official procedure and contact number for reporting maintenance requests, and what is the typical turnaround time for urgent repairs like plumbing or heating?",
        "utilities_and_services": f"Regarding {title_ref}: Could you clarify exactly which utility services (water, gas, electricity, trash, internet) are included in the base rent versus billed directly to the tenant?",
        "pets_and_animals": f"Under {title_ref}: Could you clarify the pet policy terms — specifically whether any pet fee is a refundable deposit or monthly rent, and what vaccination or registration documents are needed?",
        "parking_and_storage": f"Regarding {title_ref}: Could you confirm whether designated parking or storage spaces are assigned to this unit, and what guest parking rules or permit requirements apply?",
        "subletting_and_assignment": f"Under {title_ref}: If I need to relocate before the lease term concludes, what is the formal procedure for requesting landlord approval for a qualified replacement tenant?",
        "insurance_and_casualty": f"Regarding {title_ref}: What minimum liability coverage limits are required for renter's insurance, and is the management company required to be listed as an additional interested party?",
        "guests_and_occupancy": f"Under {title_ref}: What is the allowed duration for visiting guests before written notification to management is required?",
        "alterations_and_fixtures": f"Regarding {title_ref}: What minor decorative alterations (such as hanging artwork with standard small nails) are permitted without prior written consent?",
        "rent_escalation_and_renewal": f"Regarding {title_ref}: Will the landlord provide written notice of renewal terms and any proposed rent adjustments at least 60 days prior to lease expiration?",
        "termination_and_notice": f"Under {title_ref}: What is the required notice period for lease non-renewal, and what are the specific steps if early lease termination is needed?",
        "dispute_resolution_and_governing_law": f"Regarding {title_ref}: Can you confirm whether informal mediation or direct discussion is the initial step encouraged before any formal legal proceedings?",
        "loan_interest_and_usury": f"Regarding {title_ref}: Is this interest rate fixed for the full loan term or variable, and what is the exact APR including all origination charges?",
        "loan_prepayment_and_default": f"Under {title_ref}: Is there any prepayment penalty if I choose to pay down additional principal ahead of schedule?"
    }

    if category in low_risk_templates:
        return low_risk_templates[category]

    if default_question and not default_question.lower().startswith("no modification"):
        return f"Under {title_ref}: {default_question}"

    return f"Regarding {title_ref}: Could you confirm how this provision applies during standard day-to-day operations, and how any formal notifications or requests under this section should be submitted in writing?"


def analyze_clause_local(clause: ExtractedClause, matched_standard: Optional[Dict[str, Any]]) -> AnalyzedClause:
    """
    Local high-performance hybrid analyzer using legal rule heuristics + vector baseline comparison.
    """
    text = clause.clause_text
    title = clause.clause_title
    category = classify_clause_category(text, title)
    
    deviations = []
    risk_score = 15  # Baseline standard score
    risk_level = "low"
    is_unusual = False
    
    # Evaluate high risk triggers
    for pattern, reason, cat, score in HIGH_RISK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            deviations.append(reason)
            risk_score = max(risk_score, score)
            risk_level = "high"
            is_unusual = True
            category = cat

    # Evaluate medium risk triggers if not already high
    if risk_level != "high":
        for pattern, reason, cat, score in MEDIUM_RISK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                deviations.append(reason)
                risk_score = max(risk_score, score)
                risk_level = "medium"
                is_unusual = True
                category = cat

    # Comprehensive knowledge base: contextual explanations and questions for every clause type and risk level
    CLAUSE_KNOWLEDGE_BASE = {
        "security_deposit": {
            "high": {
                "explanation": "This deposit clause contains serious red flags — it may declare your deposit non-refundable, allow forfeiture for minor violations, or use an excessively long return timeline. You could lose your entire deposit even after a clean tenancy.",
                "question": "Can we confirm the deposit is fully refundable within 21 days of move-out, with deductions only for documented damages beyond normal wear and tear, supported by itemized receipts?",
                "baseline": "Standard lease agreements require landlords to return the security deposit within 14-30 days (varies by state), provide itemized deductions, and exclude normal wear and tear. Non-refundable deposits are illegal in many jurisdictions."
            },
            "medium": {
                "explanation": "This deposit clause has some non-standard terms that may limit your refund rights or leave the refund timeline vague. While not extreme, it gives the landlord unusual discretion.",
                "question": "Can we clarify the exact timeline for deposit return (ideally 21 days), the specific conditions that allow deductions, and confirm that normal wear and tear is explicitly excluded from deductions?",
                "baseline": "Fair deposit clauses specify a clear refund timeline (21-30 days), require itemized written receipts for any deductions, and explicitly exclude normal wear-and-tear from chargeable damages."
            },
            "low": {
                "explanation": "Your security deposit clause appears to follow standard practices. The landlord holds a deposit as financial security against unpaid rent or damages, and is expected to return it after move-out with itemized deductions if any.",
                "question": "Just to confirm: what is the exact timeline for returning my deposit after move-out, and can you confirm that normal wear and tear will not be deducted?",
                "baseline": "Standard agreements return security deposits within 14-30 days, with deductions only for damages beyond normal wear and tear, documented with itemized receipts."
            }
        },
        "termination_and_notice": {
            "high": {
                "explanation": "This termination clause is very aggressive — it may allow eviction with extremely short notice, automatic forfeiture of payments, or no opportunity for you to fix a breach before being removed. This could leave you with very little time to respond.",
                "question": "Can we ensure the lease includes a minimum 3-5 day written cure period for any alleged breach before eviction proceedings begin, and a minimum 30-day written notice for non-renewal or termination without cause?",
                "baseline": "Standard leases require landlords to provide written notice (typically 3-30 days depending on the reason) and allow tenants a reasonable period to cure a breach before eviction. Many states mandate this by law."
            },
            "medium": {
                "explanation": "This clause sets notice or termination conditions that are less favorable than typical agreements. You may have a shorter window to respond to notices or fewer protections before termination kicks in.",
                "question": "Can we add a provision for a written cure notice of at least 5 business days for any alleged violations, and confirm what the required notice period is for the landlord to terminate without cause?",
                "baseline": "Fair agreements provide at least 30 days written notice for non-renewal and 3-10 business days to cure lease violations before formal termination or eviction."
            },
            "low": {
                "explanation": "The termination and notice terms appear standard. Both you and your landlord have defined obligations about how and when to communicate lease endings, which protects both parties.",
                "question": "Can you confirm in writing what the process is if I need to break the lease early — including any fees, required notice period, or right to sublet to avoid early termination penalties?",
                "baseline": "Standard notice clauses require 30 days written notice for month-to-month and provide clear procedures for lease termination, protecting both landlord and tenant."
            }
        },
        "maintenance_and_repairs": {
            "high": {
                "explanation": "This clause attempts to shift major structural or habitability costs onto you as the tenant — things like HVAC systems, roofing, foundation, or main plumbing. This is not only unfair but may be unenforceable under housing code.",
                "question": "Can we explicitly state that the landlord is responsible for all structural systems (HVAC, roof, foundation, major plumbing, electrical), and that the tenant is only responsible for minor maintenance like changing light bulbs or air filters?",
                "baseline": "By law, landlords must maintain rental units in a habitable condition, including keeping structural systems (heating, plumbing, electricity, roof) in working order. Tenants are only responsible for minor maintenance and damage they cause."
            },
            "medium": {
                "explanation": "The maintenance responsibilities in this clause are somewhat ambiguous or assign more repair duties to you than is typical. This could result in unexpected out-of-pocket costs for repairs that should be the landlord's responsibility.",
                "question": "Can we add a clear list distinguishing tenant responsibilities (minor day-to-day maintenance) from landlord responsibilities (structural and system repairs), with a maximum dollar threshold (e.g., $150) for what counts as minor repairs?",
                "baseline": "Standard leases distinguish between tenant's minor upkeep (e.g., replacing batteries, keeping the unit clean) and landlord's structural duties (HVAC, plumbing, appliances). Most states have minimum habitability standards landlords must meet."
            },
            "low": {
                "explanation": "The maintenance clause appears fair and balanced, with typical responsibilities assigned to each party. The landlord maintains the structure and systems; you maintain the cleanliness and minor upkeep of your unit.",
                "question": "What is the process and timeline for reporting and getting maintenance issues resolved? Is there a specific number I should call, and is there a guaranteed response time for urgent repairs like heating or plumbing failures?",
                "baseline": "Standard agreements require landlords to address emergency repairs (heating, water, electricity) within 24-48 hours and routine repairs within 7-14 days of written notice."
            }
        },
        "late_fees_and_penalties": {
            "high": {
                "explanation": "This late fee clause is highly punitive — it may charge an excessive daily compounding penalty, have no grace period, or charge a flat fee far above the standard 5-10% cap. These kinds of fees may be illegal in your state.",
                "question": "Can we revise this to a standard late fee structure: a 5-day grace period after the due date, then a one-time fee not exceeding 5% of monthly rent or $50, whichever is less — with no compounding daily charges?",
                "baseline": "Most states cap late fees at 5-10% of monthly rent and require a grace period of 3-7 days. Compounding daily late fees are illegal or unenforceable in many jurisdictions."
            },
            "medium": {
                "explanation": "The late fee terms are slightly higher or stricter than what's typical in standard agreements. While not extreme, you should understand exactly when fees kick in and how they accumulate.",
                "question": "Can we confirm: what is the exact grace period (days after the due date before late fees apply), what is the late fee amount, and does it compound daily or is it a one-time charge?",
                "baseline": "Fair agreements provide at least a 5-day grace period, charge a flat late fee (typically 5% of rent or $25-50), and do not apply compounding daily penalties."
            },
            "low": {
                "explanation": "The late fee policy appears reasonable with a clear grace period and a flat fee within standard limits. Paying rent on time means you'll never be affected by these terms.",
                "question": "Just to clarify: if rent is due on the 1st, what is the last day I can pay without incurring a late fee, and is there any option to set up automatic payment to avoid this risk?",
                "baseline": "Standard agreements allow 3-7 days grace period with a flat late fee not exceeding 5-10% of one month's rent."
            }
        },
        "entry_and_privacy": {
            "high": {
                "explanation": "This clause gives the landlord the right to enter your home without advance notice or at any time of day. This is a severe violation of your right to quiet enjoyment and is illegal without notice in virtually every U.S. state.",
                "question": "Can we revise this clause to require at least 24 hours advance written notice before any non-emergency entry, specifying that entry will only occur during normal business hours (9am-6pm), with emergency access limited to genuine life/safety situations?",
                "baseline": "Almost every state requires landlords to give at least 24 hours advance written notice before entering a tenant's home, except in genuine emergencies. Unrestricted access clauses are often legally void."
            },
            "medium": {
                "explanation": "The landlord's entry rights are somewhat broader than standard, possibly allowing entry with shorter notice than the legal minimum or for reasons beyond emergencies, inspections, and repairs.",
                "question": "Can we clarify: what qualifies as an 'emergency' giving the landlord unrestricted access, and can we confirm that routine inspections or showings require a minimum of 24 hours written notice?",
                "baseline": "Standard agreements require 24-48 hours advance written notice for all non-emergency entries, limited to reasonable hours, with emergency exceptions narrowly defined."
            },
            "low": {
                "explanation": "The landlord's entry and privacy clause appears standard, requiring advance notice before entry and limiting access to reasonable hours and legitimate purposes like repairs or inspections.",
                "question": "Can you confirm the procedure for entry notifications — will I receive notice by text, email, or written letter, and is 24 hours the minimum notice I'll get before any non-emergency entry?",
                "baseline": "Standard agreements require 24 hours advance written notice before entry, limited to normal business hours and specific purposes (repairs, inspections, showing to prospective tenants)."
            }
        },
        "subletting_and_assignment": {
            "high": {
                "explanation": "This clause completely prohibits subletting or imposes severe financial penalties for unauthorized guests. This is overly restrictive and could prevent you from having family visit or from finding a subletter if your circumstances change.",
                "question": "Can we revise this to allow subletting or lease assignment with the landlord's prior written approval (not to be unreasonably withheld), as long as the proposed subtenant meets standard credit and income requirements?",
                "baseline": "Standard agreements allow subletting with landlord consent (which cannot be unreasonably withheld). Absolute bans on subletting can be challenged, especially for long-term leases."
            },
            "medium": {
                "explanation": "Subletting is allowed but with conditions or fees that are stricter than typical agreements. You may need to navigate extra steps or costs if you need to sublet during your lease term.",
                "question": "What is the process for requesting subletting approval — what documentation is required, what criteria will you use to evaluate the proposed subtenant, and are there any administrative fees involved?",
                "baseline": "Fair subletting clauses allow it with written landlord consent based on reasonable screening criteria (credit, income), without excessive fees or unreasonable denial."
            },
            "low": {
                "explanation": "The subletting provisions appear standard. You can request to sublet with landlord approval, giving you flexibility if your living situation changes during the lease term.",
                "question": "If I need to relocate before the lease ends, is subletting to a qualified person (who passes your standard screening) the preferred option, and what is the typical timeline for approval?",
                "baseline": "Standard agreements allow subletting with landlord consent, evaluated on the same screening criteria used for original tenants."
            }
        },
        "rent_escalation_and_renewal": {
            "high": {
                "explanation": "This clause could trap you in an automatic renewal at significantly higher rent if you miss a rigid opt-out window, or tie rent increases to uncapped formulas that far exceed inflation.",
                "question": "Can we cap rent increase on renewal to no more than 3-5% or the local CPI/inflation rate (whichever is lower), and reduce the opt-out notice window to 30-60 days with clear written notification from the landlord of any rent changes?",
                "baseline": "Fair renewal clauses require the landlord to notify the tenant of any rent increase at least 30-60 days before renewal, with increases tied to inflation or local market norms, not uncapped discretion."
            },
            "medium": {
                "explanation": "The lease renewal and rent escalation terms give the landlord significant discretion to raise rent at renewal. The notice period or increase cap may not be as favorable as standard agreements.",
                "question": "Can we confirm: how much advance notice will I receive before renewal with any proposed rent increase, and is there a cap on how much rent can increase per renewal period?",
                "baseline": "Standard agreements provide 30-60 days advance notice of rent changes at renewal, with increases tied to a defined formula or local market comparable rates."
            },
            "low": {
                "explanation": "The renewal and rent escalation terms appear reasonable, with clear timelines and fair conditions. You have sufficient notice to decide whether to renew and on what terms.",
                "question": "Will I receive a written renewal offer at least 60 days before the lease ends, and what is the typical rent increase percentage you apply at renewal (e.g., inflation, fixed %, or market rate)?",
                "baseline": "Standard renewal clauses provide 30-60 days advance written notice with transparent rent change calculations based on market rates or defined CPI formulas."
            }
        },
        "indemnification_and_liability": {
            "high": {
                "explanation": "This clause requires you to hold the landlord harmless even for the landlord's own negligence or intentional misconduct. This is a severe one-sided liability shift that could make you financially responsible for injuries caused by the landlord's failures.",
                "question": "Can we revise this to limit indemnification to situations caused solely by the tenant's actions or negligence, and explicitly exclude any liability for the landlord's own negligence, gross negligence, or intentional acts?",
                "baseline": "Enforceable indemnification clauses only cover damages caused by the indemnifying party's actions. Courts routinely void clauses that purport to indemnify a party against their own negligence."
            },
            "medium": {
                "explanation": "The liability clause is somewhat broad and may expose you to financial responsibility for situations that go beyond what you directly caused. It's important to understand where the boundaries of your liability begin and end.",
                "question": "Can we clarify the scope of my liability: am I only responsible for damages I or my guests directly cause through negligence, and is the landlord's liability for their own negligence or building defects excluded from my indemnity obligation?",
                "baseline": "Standard liability clauses hold each party responsible only for damages caused by their own negligence or intentional acts, not for acts outside their control."
            },
            "low": {
                "explanation": "The indemnification clause appears standard and mutual, holding each party responsible for their own negligence. This is a normal part of most rental agreements to protect both parties from third-party claims.",
                "question": "Does the landlord's insurance cover tenant property or personal injury claims if, for example, a pipe bursts due to the landlord's failure to maintain it? Or should I obtain renter's insurance to cover my belongings?",
                "baseline": "Standard agreements hold tenants responsible for their own negligence and typically recommend renters insurance for tenant's personal property, while the landlord's insurance covers the structure."
            }
        },
        "dispute_resolution_and_governing_law": {
            "high": {
                "explanation": "This clause may waive your right to a jury trial, require arbitration that favors the landlord, or mandate you pay all legal fees even if you win a dispute. These are significant legal rights you should not give up without understanding the full implications.",
                "question": "Can we remove the mandatory arbitration clause and jury trial waiver, and replace it with a mutual fee-shifting provision (loser pays attorney fees), which is more balanced and still encourages settlement without removing court access?",
                "baseline": "Fair dispute resolution clauses are mutual, allow access to courts, and don't require tenants to waive fundamental legal rights like jury trials. Mandatory arbitration clauses often favor the stronger party."
            },
            "medium": {
                "explanation": "The dispute resolution terms may require arbitration or limit your ability to sue in certain courts, which could make it harder and more expensive to resolve a dispute if one arises.",
                "question": "Can you explain the dispute resolution process step-by-step: is mediation required first, who selects and pays the arbitrator if arbitration occurs, and does each party bear its own legal fees?",
                "baseline": "Balanced agreements provide for informal resolution first, then mediation, then arbitration (with equally shared costs and neutral arbitrator selection), without waiving jury trial rights."
            },
            "low": {
                "explanation": "The dispute resolution and governing law provisions appear standard. The clause establishes which state's law governs the agreement and a straightforward process for resolving disagreements.",
                "question": "If a dispute arises, what is the first step — direct communication, formal mediation, or immediate arbitration? And does the governing law clause affect my right to file a complaint with local tenant protection agencies?",
                "baseline": "Standard agreements specify the applicable state law, encourage informal resolution first, and preserve both parties' right to use local tenant-landlord courts for small claims."
            }
        },
        "loan_interest_and_usury": {
            "high": {
                "explanation": "The interest rate in this agreement exceeds typical statutory limits or is significantly above market rates. High-interest loans can trap borrowers in a cycle of debt and may violate state usury laws.",
                "question": "Can we renegotiate the interest rate to reflect current market rates (e.g., prime rate + 2%), confirm the APR in writing as required by law, and ensure there is no compounding interest on accrued but unpaid charges?",
                "baseline": "Legal loan agreements must disclose the APR clearly. Most states cap consumer loan interest rates (18-36% depending on type). Rates exceeding these limits may be legally void."
            },
            "medium": {
                "explanation": "The interest rate or fee structure is higher than typical market rates. While possibly legal, this increases your total repayment cost significantly over the loan term.",
                "question": "Can you provide a full amortization schedule showing the total interest paid over the life of the loan, confirm the APR, and clarify whether the rate is fixed or variable and what triggers rate changes?",
                "baseline": "Fair loan agreements disclose APR clearly, use market-competitive rates, and provide full amortization schedules so borrowers understand total cost."
            },
            "low": {
                "explanation": "The loan interest terms appear within normal market range with proper disclosures. Ensure you understand whether the rate is fixed or variable, as variable rates can increase your payments over time.",
                "question": "Is this interest rate fixed for the entire loan term, or is it variable? If variable, what index is it tied to, how often can it change, and is there a maximum cap on how high it can go?",
                "baseline": "Standard loan agreements clearly state the APR, specify fixed vs. variable rate terms, and for variable rates, define the index, adjustment frequency, and rate caps."
            }
        },
        "loan_prepayment_and_default": {
            "high": {
                "explanation": "This loan clause contains extreme provisions such as a confession of judgment (waiving your right to contest a default), immediate acceleration without notice, or punishing prepayment penalties that charge you for paying off the loan early.",
                "question": "Can we remove the confession of judgment clause entirely, add a 30-day written cure period before any default acceleration, and either eliminate or cap prepayment penalties at no more than 1-2% of the remaining principal?",
                "baseline": "Federal law (CFPB) and most states restrict or prohibit confession of judgment clauses for consumer loans. Borrowers must receive written notice and a reasonable cure period before loan acceleration."
            },
            "medium": {
                "explanation": "The default and prepayment terms give the lender significant power to accelerate the loan or penalize early repayment. This could make it costly to pay off debt early or give you little time to respond to a default notice.",
                "question": "What is the cure period after a missed payment before formal default is declared, and what are the prepayment penalties — is there a window (e.g., after year 3) when prepayment becomes penalty-free?",
                "baseline": "Standard loan agreements allow 10-30 days to cure a missed payment, provide written default notice, and use declining prepayment penalties (or none) after the initial loan period."
            },
            "low": {
                "explanation": "The default and prepayment provisions appear standard, with reasonable cure periods and transparent prepayment terms. You have normal protections if you miss a payment or want to pay off early.",
                "question": "Is there any penalty for paying extra principal each month or paying off the loan ahead of schedule? And what is the exact sequence of events if I miss a payment — notice, grace period, then what?",
                "baseline": "Standard agreements allow early or extra payments without penalty (or with declining penalties), and require written default notice before any accelerated collection action."
            }
        },
        "utilities_and_services": {
            "high": {
                "explanation": "This clause may hold you responsible for building-wide utility bills without individual sub-metering, or impose severe penalties for minor utility transfer delays.",
                "question": "Can we clarify exactly which utilities are sub-metered versus master-metered, and ensure billing is based solely on actual individual unit consumption with provider statements provided?",
                "baseline": "Standard leases explicitly list tenant-paid vs. landlord-paid utilities, and require sub-metering or transparent pro-rata billing formulas for shared services."
            },
            "medium": {
                "explanation": "The utility responsibilities are somewhat ambiguous or may require tenant payment for shared area services.",
                "question": "Can we specify in writing which utilities (water, gas, electricity, trash, sewer) are covered by the rent and the expected monthly cost for any tenant-billed services?",
                "baseline": "Clear agreements designate responsibility for each specific utility service and state the payment deadlines."
            },
            "low": {
                "explanation": "The utility allocation is standard and transparent, defining typical residential utility obligations.",
                "question": "Could you clarify which utility accounts need to be put in my name prior to move-in date and whether proof of transfer is required at key pickup?",
                "baseline": "Standard leases require tenants to transfer electric/gas into their name upon occupancy while water/trash are often covered or billed predictably."
            }
        },
        "pets_and_animals": {
            "high": {
                "explanation": "This pet clause imposes severe non-refundable forfeiture fees or unrestricted landlord authority to demand immediate pet removal without violation.",
                "question": "Can we amend this to ensure that any pet fee is defined as a refundable damage deposit (rather than forfeiture) and that pet removal can only be required for documented, uncured nuisance or aggression?",
                "baseline": "Standard pet addenda use reasonable refundable pet deposits ($200-$400) and specify documented nuisance procedures before any removal requirement."
            },
            "medium": {
                "explanation": "The pet terms involve high monthly pet rent or strict breed/weight restrictions that may limit your pet options.",
                "question": "Can we confirm: what are the exact monthly pet rent amounts, is the pet deposit refundable upon move-out inspection, and what registration forms are needed?",
                "baseline": "Fair pet agreements charge either a modest refundable deposit or reasonable pet rent ($25-$50/month) with transparent rules."
            },
            "low": {
                "explanation": "The pet rules appear standard and reasonable, outlining basic guidelines for keeping pets on the premises.",
                "question": "Could you confirm whether the pet deposit is refundable if no damage occurs, and whether there are designated pet relief areas on the property?",
                "baseline": "Standard agreements outline pet screening, vaccination records, and deposit return conditions."
            }
        },
        "parking_and_storage": {
            "high": {
                "explanation": "This clause allows immediate vehicle towing without notice, disclaims all liability for parking facility security, or imposes excessive unreserved parking charges.",
                "question": "Can we add a provision that at least 24 hours advance warning or notice will be given before towing any tenant-registered vehicle, except when blocking emergency access?",
                "baseline": "Standard leases require prior written notice or tagging before towing tenant vehicles, except in fire lane or emergency blockage situations."
            },
            "medium": {
                "explanation": "Parking rights or storage terms may not guarantee an assigned space or may include vague extra fee provisions.",
                "question": "Can we confirm the designated parking space number in the lease and clarify if guest parking passes are provided free of charge?",
                "baseline": "Fair agreements identify assigned parking stalls clearly and provide reasonable visitor parking arrangements."
            },
            "low": {
                "explanation": "The parking and storage terms are standard, providing clear rules for vehicle registration and facility use.",
                "question": "Could you confirm my assigned stall number and the procedure for obtaining parking decals or visitor parking passes?",
                "baseline": "Standard leases specify assigned space numbers, vehicle condition rules, and permit procedures."
            }
        },
        "insurance_and_casualty": {
            "high": {
                "explanation": "This clause forces the tenant to waive all claims even if building casualty or fire is caused by the landlord's lack of maintenance.",
                "question": "Can we clarify that while the tenant maintains renter's insurance for personal property, the landlord's structural insurance covers damages caused by landlord system failures (e.g. burst aging pipes)?",
                "baseline": "Standard agreements require tenants to insure personal contents, while landlords maintain structural casualty and liability coverage for building systems."
            },
            "medium": {
                "explanation": "The insurance requirements mandate unusually high liability coverage limits or restrictive insurer ratings.",
                "question": "Can we confirm the minimum liability coverage required (e.g. $100,000) and whether listing the landlord as an 'additional interested party' is sufficient?",
                "baseline": "Standard leases typically require $100,000 personal liability renter's insurance."
            },
            "low": {
                "explanation": "The renter's insurance requirement is standard and protects both tenant personal belongings and minor liability.",
                "question": "What is the deadline for submitting proof of renter's insurance, and what specific naming format is needed for the property management entry?",
                "baseline": "Standard residential leases require standard $100k liability renter's insurance prior to key handover."
            }
        },
        "guests_and_occupancy": {
            "high": {
                "explanation": "This clause restricts guest stays to unreasonably short periods (e.g. 2-3 days) or threatens immediate eviction and fines for visiting family members.",
                "question": "Can we revise the guest policy to allow visitors for up to 14 consecutive days or 30 days total per year before requiring landlord registration?",
                "baseline": "Standard leases permit guests for 10-14 consecutive days without requiring landlord approval or fee additions."
            },
            "medium": {
                "explanation": "Guest rules are somewhat strict regarding visitor parking, amenity access, or notice timelines.",
                "question": "What is the specific procedure if an out-of-town guest stays for more than a few days, and do they need a temporary visitor pass?",
                "baseline": "Fair guest policies allow reasonable family/friend visits while protecting community quiet enjoyment."
            },
            "low": {
                "explanation": "The guest and occupancy terms appear standard, defining resident household limits and reasonable visitor guidelines.",
                "question": "Can you confirm the guest policy guidelines regarding pool/gym amenity access and guest parking allowances?",
                "baseline": "Standard leases allow guests to visit with tenant accompaniment and establish standard 14-day stay guidelines."
            }
        },
        "alterations_and_fixtures": {
            "high": {
                "explanation": "This clause completely forbids hanging pictures, curtains, or minor decoration and threatens deposit forfeiture for minor nail holes.",
                "question": "Can we clarify that standard picture hangers, small nail holes, and temporary window coverings are permitted and considered normal wear and tear if patched upon move-out?",
                "baseline": "Standard agreements allow reasonable non-structural decorative hanging (small nail holes) and require tenant restoration upon move-out."
            },
            "medium": {
                "explanation": "Alteration restrictions require written landlord consent even for minor cosmetic additions.",
                "question": "Can we confirm what minor wall hangings (e.g., small nails for frames or adhesive strips) are allowed without formal written approval?",
                "baseline": "Fair leases differentiate between major alterations (painting, drilling into tile) and standard residential decorating."
            },
            "low": {
                "explanation": "The alterations clause is standard, prohibiting major structural modifications while maintaining the unit's condition.",
                "question": "Could you confirm whether mounting a television or painting accent walls is allowed with prior approval and restoring original paint before move-out?",
                "baseline": "Standard contracts require prior written consent for structural changes and wall painting."
            }
        },
        "rent_payment": {
            "high": {
                "explanation": "This clause mandates payment only through proprietary services with exorbitant transaction surcharges or restricts payment methods unreasonably.",
                "question": "Can we ensure that at least one fee-free payment method (such as ACH direct transfer or paper check) is always available for paying rent?",
                "baseline": "Many states require landlords to offer at least one fee-free method to pay monthly rent."
            },
            "medium": {
                "explanation": "Payment terms may lack clarity regarding online portal maintenance, processing delays, or receipt issuance.",
                "question": "Can we confirm: if the online payment portal experiences technical downtime, will tenants receive an automatic grace period extension without late fees?",
                "baseline": "Fair agreements provide relief from late fees if payment delays result from landlord portal technical failures."
            },
            "low": {
                "explanation": "The rent payment terms are clear and standard, establishing the due date, grace period, and payment process.",
                "question": "What payment methods are supported through the resident portal, and is there an option to set up automated recurring ACH payments?",
                "baseline": "Standard leases state rent amount, monthly due date (typically the 1st), and available payment methods."
            }
        },
        "general": {
            "high": {
                "explanation": "This clause contains unusual or one-sided terms that create significant obligations or restrictions beyond standard contract practice. It may limit your rights or create financial exposure in ways that aren't immediately obvious.",
                "question": "Can you explain the practical effect of this clause in plain terms, and can we discuss whether more balanced, mutually protective language could achieve the same legitimate purpose?",
                "baseline": "Standard contractual provisions are mutual, proportionate to the risk each party takes on, and aligned with consumer protection norms in the applicable jurisdiction."
            },
            "medium": {
                "explanation": "This clause has some terms that are less favorable than typical agreements or that give the other party more discretion than is usually standard. It's worth clarifying or negotiating before signing.",
                "question": "Can we clarify the scope and limits of this clause — specifically, under what circumstances would it be triggered, and can we add any language to make the obligations more mutual and defined?",
                "baseline": "Fair contractual clauses are clear, specific, and proportionate. Vague or open-ended obligations favor the drafter of the contract."
            },
            "low": {
                "explanation": "This clause appears to be standard contractual boilerplate establishing the basic framework of the agreement between the parties. It's important to read and understand all provisions even when they appear routine.",
                "question": "Can you walk me through what this clause means in practice — when would it apply, and are there any scenarios where it could create unexpected obligations for me as the tenant/borrower?",
                "baseline": "Standard boilerplate clauses establish the legal framework (governing law, entire agreement, severability, modifications in writing) and are generally mutual and enforceable."
            }
        }
    }

    # Generate plain-language explanation and questions
    explanation = ""
    suggested_question = ""
    baseline_summary = ""
    standard_id = None

    if matched_standard:
        standard_id = matched_standard.get("id")
        baseline_summary = matched_standard.get("standard_acceptable_range", matched_standard.get("baseline_text", ""))

    # Get the knowledge base entry for this category (fallback to "general")
    cat_kb = CLAUSE_KNOWLEDGE_BASE.get(category, CLAUSE_KNOWLEDGE_BASE["general"])
    kb_entry = cat_kb.get(risk_level, cat_kb.get("low"))

    # Generate context-aware tailored question
    suggested_question = generate_tailored_clause_question(
        clause_title=title,
        clause_text=text,
        category=category,
        risk_level=risk_level,
        is_unusual=is_unusual,
        deviations=deviations,
        default_question=kb_entry.get("question", "")
    )

    if is_unusual:
        deviation_prefix = ""
        if deviations:
            dev_list = "; ".join(deviations[:2])
            deviation_prefix = f"Specifically: {dev_list}. "
        explanation = deviation_prefix + kb_entry["explanation"]
        if not baseline_summary:
            baseline_summary = kb_entry["baseline"]
    else:
        explanation = kb_entry["explanation"]
        if not baseline_summary:
            baseline_summary = kb_entry["baseline"]

    return AnalyzedClause(
        clause_id=clause.clause_id,
        clause_number=clause.clause_number,
        clause_title=clause.clause_title,
        clause_text=clause.clause_text,
        clause_type=category,
        is_unusual=is_unusual,
        risk_level=risk_level,
        risk_score=risk_score,
        plain_language_explanation=explanation,
        deviation_points=deviations,
        suggested_question_to_ask_landlord=suggested_question,
        standard_baseline_comparison=baseline_summary or "Standard contractual baseline.",
        matched_standard_id=standard_id,
        validation_audit=ValidationAudit(
            is_validated=False,
            initial_risk=risk_level,
            final_risk=risk_level
        )
    )


def analyze_clause_with_gemini(clause: ExtractedClause, matched_standard: Optional[Dict[str, Any]], api_key: str) -> Optional[AnalyzedClause]:
    """Calls Google Gemini API for structured clause risk assessment."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    standard_context = ""
    if matched_standard:
        standard_context = f"Baseline Standard: {matched_standard.get('baseline_text', '')}\nAcceptable Range: {matched_standard.get('standard_acceptable_range', '')}"

    prompt = f"""You are a specialized Legal Document Risk Analyst.
Analyze the following legal clause against the standard contract baseline.

Target Clause to Analyze:
Title: {clause.clause_title}
Text: {clause.clause_text}

{standard_context}

Return a valid JSON object matching this schema:
{{
  "clause_type": "security_deposit | termination_and_notice | maintenance_and_repairs | late_fees_and_penalties | entry_and_privacy | subletting_and_assignment | rent_escalation_and_renewal | indemnification_and_liability | dispute_resolution_and_governing_law | loan_interest_and_usury | loan_prepayment_and_default | general",
  "is_unusual": boolean,
  "risk_level": "low" | "medium" | "high",
  "risk_score": integer between 0 and 100,
  "plain_language_explanation": "Simple, clear 2-3 sentence layman explanation",
  "deviation_points": ["Specific deviation 1", "Specific deviation 2"],
  "suggested_question_to_ask_landlord": "Practical negotiation question for tenant/borrower",
  "standard_baseline_comparison": "Brief summary of what standard fair agreements say"
}}
Output ONLY raw JSON. No markdown codeblocks, no commentary."""

    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
        }
        res = requests.post(url, json=payload, timeout=12)
        if res.status_code == 200:
            data = res.json()
            raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json.strip(), flags=re.DOTALL).strip()
            parsed = json.loads(clean)
            c_type = parsed.get("clause_type", "general")
            r_level = parsed.get("risk_level", "low")
            is_u = bool(parsed.get("is_unusual", False))
            devs = parsed.get("deviation_points", [])
            question = (parsed.get("suggested_question_to_ask_landlord") or "").strip()
            if not question or question.lower().startswith("no modification"):
                question = generate_tailored_clause_question(
                    clause_title=clause.clause_title,
                    clause_text=clause.clause_text,
                    category=c_type,
                    risk_level=r_level,
                    is_unusual=is_u,
                    deviations=devs
                )
            return AnalyzedClause(
                clause_id=clause.clause_id,
                clause_number=clause.clause_number,
                clause_title=clause.clause_title,
                clause_text=clause.clause_text,
                clause_type=c_type,
                is_unusual=is_u,
                risk_level=r_level,
                risk_score=int(parsed.get("risk_score", 20)),
                plain_language_explanation=parsed.get("plain_language_explanation", ""),
                deviation_points=devs,
                suggested_question_to_ask_landlord=question,
                standard_baseline_comparison=parsed.get("standard_baseline_comparison", ""),
                matched_standard_id=matched_standard.get("id") if matched_standard else None
            )
    except Exception:
        pass
    return None


def _build_llm_prompt(clause: ExtractedClause, matched_standard: Optional[Dict[str, Any]]) -> str:
    """Shared prompt builder for all LLM providers."""
    standard_context = ""
    if matched_standard:
        standard_context = f"Baseline Standard: {matched_standard.get('baseline_text', '')}\nAcceptable Range: {matched_standard.get('standard_acceptable_range', '')}"

    return f"""You are a specialized Legal Document Risk Analyst helping a tenant or borrower understand their contract.
Analyze the following legal clause and return a structured JSON risk assessment.

Clause Title: {clause.clause_title}
Clause Text: {clause.clause_text}

{standard_context}

Return ONLY a valid JSON object with these exact fields:
{{
  "clause_type": "one of: security_deposit | termination_and_notice | maintenance_and_repairs | late_fees_and_penalties | entry_and_privacy | subletting_and_assignment | rent_escalation_and_renewal | indemnification_and_liability | dispute_resolution_and_governing_law | utilities_and_services | pets_and_animals | parking_and_storage | insurance_and_casualty | guests_and_occupancy | alterations_and_fixtures | rent_payment | loan_interest_and_usury | loan_prepayment_and_default | general",
  "is_unusual": true or false,
  "risk_level": "low" or "medium" or "high",
  "risk_score": integer 0-100 (0=harmless, 100=severely predatory),
  "plain_language_explanation": "2-3 sentence plain-English explanation of what this clause means for the tenant/borrower",
  "deviation_points": ["specific deviation from standard practice 1", "deviation 2"],
  "suggested_question_to_ask_landlord": "A specific, polite, practical negotiation question the tenant should ask before signing",
  "standard_baseline_comparison": "What fair standard agreements typically say on this topic"
}}
Output ONLY raw JSON. No markdown, no code fences, no commentary."""


def _parse_llm_json(raw: str, clause: ExtractedClause, matched_standard: Optional[Dict[str, Any]]) -> Optional[AnalyzedClause]:
    """Parses LLM JSON response into an AnalyzedClause object."""
    try:
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL).strip()
        parsed = json.loads(clean)
        c_type = parsed.get("clause_type", "general")
        r_level = parsed.get("risk_level", "low")
        is_u = bool(parsed.get("is_unusual", False))
        devs = parsed.get("deviation_points", [])
        question = (parsed.get("suggested_question_to_ask_landlord") or "").strip()
        if not question or question.lower().startswith("no modification"):
            question = generate_tailored_clause_question(
                clause_title=clause.clause_title,
                clause_text=clause.clause_text,
                category=c_type,
                risk_level=r_level,
                is_unusual=is_u,
                deviations=devs
            )

        return AnalyzedClause(
            clause_id=clause.clause_id,
            clause_number=clause.clause_number,
            clause_title=clause.clause_title,
            clause_text=clause.clause_text,
            clause_type=c_type,
            is_unusual=is_u,
            risk_level=r_level,
            risk_score=max(0, min(100, int(parsed.get("risk_score", 20)))),
            plain_language_explanation=parsed.get("plain_language_explanation", ""),
            deviation_points=devs,
            suggested_question_to_ask_landlord=question,
            standard_baseline_comparison=parsed.get("standard_baseline_comparison", ""),
            matched_standard_id=matched_standard.get("id") if matched_standard else None,
            validation_audit=ValidationAudit(is_validated=True, initial_risk="unknown", final_risk=r_level)
        )
    except Exception:
        return None


def analyze_clause_with_groq(clause: ExtractedClause, matched_standard: Optional[Dict[str, Any]], api_key: str) -> Optional[AnalyzedClause]:
    """Calls Groq API (OpenAI-compatible) for LLM-powered structured clause analysis."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    prompt = _build_llm_prompt(clause, matched_standard)
    groq_model = os.environ.get("GROQ_MODEL") or getattr(config, "GROQ_MODEL", "openai/gpt-oss-120b")
    payload = {
        "model": groq_model,
        "messages": [
            {"role": "system", "content": "You are an expert legal document analyst for tenants and consumers. Always respond with only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"}
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=20)
        if res.status_code == 200:
            raw = res.json()["choices"][0]["message"]["content"]
            result = _parse_llm_json(raw, clause, matched_standard)
            if result:
                return result
        else:
            print(f"[Groq] API error {res.status_code}: {res.text[:200]}")
    except Exception as e:
        print(f"[Groq] Request failed: {e}")
    return None


def analyze_clause(clause: ExtractedClause, provider: Optional[str] = None) -> AnalyzedClause:
    """
    Main entry point for analyzing a single extracted clause.
    Retrieves standard baselines from vector store and processes through chosen engine.
    """
    store = get_clause_store()
    retrieved = store.retrieve_top_k(clause.clause_text, k=1)
    matched_standard = retrieved[0] if retrieved else None

    # Dynamically resolve active keys
    groq_key = _get_active_groq_key()
    gemini_key = _get_active_gemini_key()
    active_provider = provider or getattr(config, "DEFAULT_PROVIDER", "groq")

    # Groq: try whenever a key exists, unless local-only analysis was requested
    if groq_key and active_provider != "local":
        groq_res = analyze_clause_with_groq(clause, matched_standard, groq_key)
        if groq_res:
            return groq_res

    # Gemini: fallback if Groq unavailable and Gemini key exists
    if gemini_key and active_provider != "local" and (active_provider == "gemini" or not groq_key):
        gemini_res = analyze_clause_with_gemini(clause, matched_standard, gemini_key)
        if gemini_res:
            return gemini_res

    # Final fallback: Local Hybrid Rule Engine with tailored questions
    return analyze_clause_local(clause, matched_standard)
