import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure project root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import backend.config as config
from backend.config import FRONTEND_DIR, SAMPLES_DIR, DEFAULT_PROVIDER, GEMINI_API_KEY, GROQ_API_KEY, set_runtime_api_key, set_groq_api_key
from backend.ingestion.extractor import extract_text_from_file
from backend.ingestion.chunker import chunk_legal_document
from backend.knowledge_base.vector_store import get_clause_store
from backend.analyzer.schemas import AnalysisResponse, DocumentAnalysisSummary, AnalyzedClause
from backend.analyzer.comparator import analyze_clause
from backend.analyzer.validator import run_validation_pass
from backend.evaluation.eval_pipeline import run_evaluation_benchmark
from backend.auth.database import init_db, save_user_analysis
from backend.auth.security import get_current_user, get_optional_user
from backend.auth.router import router as auth_router
from backend.request_limits import RequestSizeLimitMiddleware, limiter

logger = logging.getLogger("clauseclear")

# Initialize database schema and default records
init_db()

app = FastAPI(
    title="ClauseClear API",
    description="Legal Document Simplifier & Risk Analyzer Backend",
    version="1.0.0",
    debug=config.DEBUG,
    docs_url="/docs" if config.IS_DEVELOPMENT else None,
    redoc_url=None,
    openapi_url="/openapi.json" if config.IS_DEVELOPMENT else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=config.MAX_REQUEST_BYTES)

# Register Authentication & User Management router
app.include_router(auth_router)

# CORS middleware for development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Dev-only Swagger UI loads assets from a CDN that the policy would block.
    if not (config.IS_DEVELOPMENT and request.url.path in ("/docs", "/openapi.json")):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not config.IS_DEVELOPMENT:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class TextAnalysisRequest(BaseModel):
    text: str
    document_title: Optional[str] = "Pasted Legal Document"
    provider: Optional[str] = None


class EvalRequest(BaseModel):
    provider: Optional[str] = "local"


class ApiKeyUpdateRequest(BaseModel):
    gemini_api_key: str


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config_status():
    """Checks which LLM providers are configured."""
    gemini_key = (os.getenv("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", "") or "").strip()
    groq_key = (os.getenv("GROQ_API_KEY") or getattr(config, "GROQ_API_KEY", "") or "").strip()
    return {
        "gemini_configured": bool(gemini_key and len(gemini_key) > 5),
        "groq_configured": bool(groq_key and len(groq_key) > 5),
        "default_provider": DEFAULT_PROVIDER,
        "active_provider": "groq" if (groq_key and len(groq_key) > 5) else ("gemini" if (gemini_key and len(gemini_key) > 5) else "local"),
        "runtime_api_key_updates_enabled": config.RUNTIME_API_KEY_UPDATES_ENABLED,
        "demo_login_enabled": config.DEMO_LOGIN_ENABLED
    }


@app.post("/api/config/key")
async def update_api_key(req: ApiKeyUpdateRequest):
    """Allows setting runtime Gemini API key directly from the UI."""
    if not config.RUNTIME_API_KEY_UPDATES_ENABLED:
        raise HTTPException(status_code=404, detail="Runtime provider-key updates are disabled.")
    if not req.gemini_api_key or len(req.gemini_api_key.strip()) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key format")
    set_runtime_api_key(req.gemini_api_key.strip())
    return {"status": "success", "message": "Gemini API key updated successfully."}


class GroqKeyUpdateRequest(BaseModel):
    groq_api_key: str


@app.post("/api/config/groq-key")
async def update_groq_api_key(req: GroqKeyUpdateRequest):
    """Allows setting Groq API key at runtime from the UI — tests validity and saves."""
    if not config.RUNTIME_API_KEY_UPDATES_ENABLED:
        raise HTTPException(status_code=404, detail="Runtime provider-key updates are disabled.")
    key = req.groq_api_key.strip()
    if not key or len(key) < 15:
        raise HTTPException(status_code=400, detail="Invalid Groq API key format (must start with gsk_)")
    
    # Verify key with Groq API
    try:
        import requests
        test_res = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8
        )
        if test_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Groq rejected this API key: Status {test_res.status_code} ({test_res.text[:100]})")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Warning: could not verify Groq key online: {e}")

    set_groq_api_key(key)
    return {
        "status": "success",
        "message": "Groq API key verified and activated successfully! LLaMA 3.3 70B analysis is now running.",
        "provider": "groq"
    }


def process_document_pipeline(text: str, document_title: str, provider: Optional[str] = None) -> AnalysisResponse:
    """Executes the complete ClauseClear ingestion, retrieval, analysis, and validation pipeline."""
    start_time = time.time()
    
    # 1. Chunk document by clause boundaries
    extracted_clauses = chunk_legal_document(text)
    
    if not extracted_clauses:
        raise HTTPException(status_code=400, detail="No readable legal clauses found in document.")

    analyzed_clauses: List[AnalyzedClause] = []
    
    low_count = 0
    med_count = 0
    high_count = 0
    unusual_count = 0
    risk_scores = []
    red_flags = []

    # 2. Analyze each clause & execute Stage 2 validation for high-risk clauses
    for clause in extracted_clauses:
        # Stage 1: Retrieval + Comparison
        analyzed = analyze_clause(clause, provider=provider)
        
        # Stage 2: Anti-Hallucination / False-Positive Validation Pass
        validated = run_validation_pass(analyzed, provider=provider)
        
        analyzed_clauses.append(validated)
        
        # Aggregate statistics
        risk_scores.append(validated.risk_score)
        if validated.is_unusual:
            unusual_count += 1
            
        if validated.risk_level == "high":
            high_count += 1
            if validated.deviation_points:
                red_flags.extend(validated.deviation_points)
            else:
                red_flags.append(f"{validated.clause_title}: Non-standard terms detected.")
        elif validated.risk_level == "medium":
            med_count += 1
        else:
            low_count += 1

    elapsed = round(time.time() - start_time, 3)
    
    # Calculate overall document risk score
    if high_count > 0:
        overall_score = min(100, int(sum(risk_scores) / len(risk_scores) + (high_count * 15)))
    else:
        overall_score = int(sum(risk_scores) / len(risk_scores)) if risk_scores else 0

    if overall_score >= 70 or high_count >= 2:
        verdict = "HIGH RISK: Contains multiple predatory or non-standard provisions that pose significant legal and financial hazards."
    elif overall_score >= 40 or med_count >= 2:
        verdict = "MODERATE RISK: Generally acceptable but includes clauses that warrant clarification or negotiation."
    else:
        verdict = "LOW RISK / FAIR: Terms closely match standard market baselines and consumer protection norms."

    summary = DocumentAnalysisSummary(
        total_clauses=len(analyzed_clauses),
        low_risk_count=low_count,
        medium_risk_count=med_count,
        high_risk_count=high_count,
        unusual_clause_count=unusual_count,
        overall_risk_score=overall_score,
        overall_verdict=verdict,
        key_red_flags=list(dict.fromkeys(red_flags))[:5]  # Deduplicated top 5
    )

    # Determine what provider was actually used
    groq_key = (os.getenv("GROQ_API_KEY") or getattr(config, "GROQ_API_KEY", "") or "").strip()
    gemini_key = (os.getenv("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", "") or "").strip()
    if groq_key and len(groq_key) > 10:
        actual_provider = "groq"
    elif gemini_key and len(gemini_key) > 10 and provider == "gemini":
        actual_provider = "gemini"
    else:
        actual_provider = "local"

    return AnalysisResponse(
        document_title=document_title,
        summary=summary,
        clauses=analyzed_clauses,
        processing_time_seconds=elapsed,
        llm_provider_used=actual_provider
    )


@app.post("/api/analyze/file", response_model=AnalysisResponse)
@limiter.limit("10/hour")
async def analyze_file(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    provider: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Uploads a PDF, TXT, or image legal contract and performs clause-by-clause analysis."""
    try:
        filename = file.filename or ""
        if Path(filename).suffix.lower() not in {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"}:
            raise HTTPException(status_code=415, detail="Supported file types are PDF, TXT, MD, PNG, JPG, and JPEG.")

        content_bytes = await file.read(config.MAX_REQUEST_BYTES + 1)
        if len(content_bytes) > config.MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit.")

        extension = Path(filename).suffix.lower()
        expected_signatures = {
            ".pdf": content_bytes.startswith(b"%PDF-"),
            ".png": content_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
            ".jpg": content_bytes.startswith(b"\xff\xd8\xff"),
            ".jpeg": content_bytes.startswith(b"\xff\xd8\xff"),
        }
        if extension in expected_signatures and not expected_signatures[extension]:
            raise HTTPException(status_code=415, detail="Uploaded file content does not match its filename type.")

        extracted_text, metadata = extract_text_from_file(filename, content_bytes)
        if metadata.get("type") == "image" and extracted_text.startswith("Image OCR requires"):
            raise HTTPException(status_code=415, detail="Image OCR is not configured on this service.")
        
        if not extracted_text or len(extracted_text.strip()) < 30:
            raise HTTPException(status_code=400, detail="Could not extract sufficient text from the uploaded file.")
            
        doc_title = Path(file.filename).stem.replace("_", " ").title() if file.filename else "Uploaded Contract"
        result = process_document_pipeline(extracted_text, doc_title, provider=provider)

        if current_user:
            try:
                save_user_analysis(
                    user_id=current_user["id"],
                    document_title=result.document_title,
                    overall_risk_score=result.summary.overall_risk_score,
                    total_clauses=result.summary.total_clauses,
                    high_risk_count=result.summary.high_risk_count,
                    summary_verdict=result.summary.overall_verdict,
                    analysis_data=result.model_dump()
                )
            except Exception as err:
                print(f"Auto-save to history failed: {err}")

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Document processing failed")
        raise HTTPException(status_code=500, detail="Unable to process this document.")


@app.post("/api/analyze/text", response_model=AnalysisResponse)
@limiter.limit("10/hour")
async def analyze_text(
    request: Request,
    response: Response,
    analysis_request: TextAnalysisRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Analyzes raw text of a legal document."""
    if not analysis_request.text or len(analysis_request.text.strip()) < 30:
        raise HTTPException(status_code=400, detail="Text is too short to analyze.")
        
    try:
        result = process_document_pipeline(
            analysis_request.text,
            analysis_request.document_title or "Pasted Legal Document",
            provider=analysis_request.provider,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Pasted text analysis failed")
        raise HTTPException(status_code=500, detail="Unable to analyze this text.")

    if current_user:
        try:
            save_user_analysis(
                user_id=current_user["id"],
                document_title=result.document_title,
                overall_risk_score=result.summary.overall_risk_score,
                total_clauses=result.summary.total_clauses,
                high_risk_count=result.summary.high_risk_count,
                summary_verdict=result.summary.overall_verdict,
                analysis_data=result.model_dump()
            )
        except Exception as err:
            print(f"Auto-save to history failed: {err}")

    return result


@app.get("/api/kb/clauses")
async def get_standard_clauses(category: Optional[str] = None):
    """Returns curated baseline standard clauses from the vector knowledge base."""
    store = get_clause_store()
    clauses = store.get_all_clauses()
    if category:
        clauses = [c for c in clauses if c["category"] == category]
    return {"count": len(clauses), "clauses": clauses}


@app.post("/api/eval/run")
@limiter.limit("3/hour")
async def run_evaluation(
    request: Request,
    response: Response,
    evaluation_request: Optional[EvalRequest] = None,
):
    """Executes the evaluation benchmark suite against the 20 labeled ground-truth clauses."""
    provider = evaluation_request.provider if evaluation_request else "local"
    try:
        results = run_evaluation_benchmark(provider=provider)
        return JSONResponse(content=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@app.get("/api/samples")
async def get_sample_documents():
    """Returns metadata and text for preloaded sample contracts."""
    sample_files = [
        {
            "id": "predatory_lease",
            "name": "Predatory Residential Lease (High Risk Trap)",
            "type": "Rental Agreement",
            "file": "predatory_rental_lease.txt",
            "expected_risk": "high",
            "description": "Contains non-refundable deposit, 24/7 unannounced entry, $75/day late fees, and habitability waiver."
        },
        {
            "id": "standard_lease",
            "name": "Standard Fair Lease (Market Baseline)",
            "type": "Rental Agreement",
            "file": "standard_fair_lease.txt",
            "expected_risk": "low",
            "description": "Standard balanced rental agreement adhering to consumer protections and statutory notice periods."
        },
        {
            "id": "predatory_loan",
            "name": "Predatory Promissory Note (Aggressive Lender Terms)",
            "type": "Loan Agreement",
            "file": "predatory_loan_agreement.txt",
            "expected_risk": "high",
            "description": "Contains 48% usury APR, confession of judgment, and 5-year unearned interest prepayment penalty."
        }
    ]

    for s in sample_files:
        path = SAMPLES_DIR / s["file"]
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                s["preview"] = f.read(400) + "..."
                s["full_text"] = f.read() if False else None  # load on request

    return {"samples": sample_files}


@app.get("/api/samples/{sample_id}")
async def get_sample_content(sample_id: str):
    """Returns the full text of a specific sample document."""
    mapping = {
        "predatory_lease": "predatory_rental_lease.txt",
        "standard_lease": "standard_fair_lease.txt",
        "predatory_loan": "predatory_loan_agreement.txt"
    }
    
    if sample_id not in mapping:
        raise HTTPException(status_code=404, detail="Sample not found")
        
    path = SAMPLES_DIR / mapping[sample_id]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Sample file missing")
        
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        
    return {"id": sample_id, "filename": mapping[sample_id], "text": content}


# Mount frontend static files
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(
                str(index_path),
                headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
            )
        return {"message": "ClauseClear API is running. Frontend index.html not found."}


if __name__ == "__main__":
    import uvicorn
    from backend.config import HOST, PORT
    uvicorn.run("backend.app:app", host=HOST, port=PORT, reload=False)
