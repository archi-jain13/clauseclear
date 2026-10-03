from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class ValidationAudit(BaseModel):
    is_validated: bool = Field(default=False, description="Whether a 2nd stage self-consistency validation check was performed.")
    initial_risk: Optional[str] = Field(default=None, description="Initial risk level before verification")
    final_risk: Optional[str] = Field(default=None, description="Final risk level after verification")
    is_false_positive: bool = Field(default=False, description="True if initial flag was determined to be standard legal boilerplate rather than genuinely predatory")
    validator_notes: str = Field(default="", description="Reasoning from the self-consistency check")


class AnalyzedClause(BaseModel):
    clause_id: str
    clause_number: str
    clause_title: str
    clause_text: str
    clause_type: str = Field(
        description="Legal domain category e.g. security_deposit, termination_and_notice, maintenance_and_repairs, late_fees_and_penalties, entry_and_privacy, subletting_and_assignment, rent_escalation_and_renewal, indemnification_and_liability, dispute_resolution_and_governing_law, loan_interest_and_usury, loan_prepayment_and_default, general"
    )
    is_unusual: bool = Field(description="True if the clause deviates significantly from standard commercial/consumer norms")
    risk_level: Literal["low", "medium", "high"] = Field(description="Risk assessment: low (fair/standard), medium (caution/unfavorable), high (predatory/onerous/illegal)")
    risk_score: int = Field(ge=0, le=100, description="Risk score from 0 (harmless) to 100 (severe hazard)")
    plain_language_explanation: str = Field(description="Clear, jargon-free explanation for a layperson")
    deviation_points: List[str] = Field(default_factory=list, description="Specific terms that deviate from normal baseline contracts")
    suggested_question_to_ask_landlord: str = Field(description="Negotiation question or counter-proposal to ask landlord/lender")
    standard_baseline_comparison: str = Field(description="Summary of what standard fair agreements stipulate for this topic")
    matched_standard_id: Optional[str] = None
    validation_audit: ValidationAudit = Field(default_factory=ValidationAudit)


class DocumentAnalysisSummary(BaseModel):
    total_clauses: int
    low_risk_count: int
    medium_risk_count: int
    high_risk_count: int
    unusual_clause_count: int
    overall_risk_score: int = Field(ge=0, le=100)
    overall_verdict: str
    key_red_flags: List[str]


class AnalysisResponse(BaseModel):
    document_title: str
    summary: DocumentAnalysisSummary
    clauses: List[AnalyzedClause]
    processing_time_seconds: float
    llm_provider_used: str
