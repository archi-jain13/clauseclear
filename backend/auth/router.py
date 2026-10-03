import re
from typing import Optional, List, Dict, Any
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Depends, Request, Response, status
from pydantic import BaseModel, Field
from backend.config import DEMO_LOGIN_ENABLED
from backend.request_limits import limiter

try:
    from backend.auth.database import (
        create_user,
        get_user_by_email,
        get_user_by_id,
        save_user_analysis,
        get_user_analyses,
        get_user_analysis_by_id,
        delete_user_analysis
    )
    from backend.auth.security import (
        hash_password,
        verify_password,
        create_access_token,
        get_current_user
    )
except ImportError:
    try:
        from .database import (
            create_user,
            get_user_by_email,
            get_user_by_id,
            save_user_analysis,
            get_user_analyses,
            get_user_analysis_by_id,
            delete_user_analysis
        )
        from .security import (
            hash_password,
            verify_password,
            create_access_token,
            get_current_user
        )
    except ImportError:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from backend.auth.database import (
            create_user,
            get_user_by_email,
            get_user_by_id,
            save_user_analysis,
            get_user_analyses,
            get_user_analysis_by_id,
            delete_user_analysis
        )
        from backend.auth.security import (
            hash_password,
            verify_password,
            create_access_token,
            get_current_user
        )

router = APIRouter(prefix="/api", tags=["Authentication & User Management"])


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=6, max_length=100)


class UserLoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    created_at: Optional[str] = None


class AuthResponse(BaseModel):
    status: str
    message: str
    token: str
    user: UserResponse


class SaveAnalysisHistoryRequest(BaseModel):
    document_title: str
    overall_risk_score: int
    total_clauses: int
    high_risk_count: int
    summary_verdict: Optional[str] = None
    analysis: Dict[str, Any]


def validate_email_format(email: str) -> bool:
    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return bool(re.match(email_regex, email.strip()))


@router.post("/auth/register", response_model=AuthResponse)
@limiter.limit("10/hour")
async def register(request: Request, response: Response, req: UserRegisterRequest):
    """Registers a new user account and returns an active JWT session token."""
    email = req.email.strip().lower()
    if not validate_email_format(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address format."
        )

    if len(req.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long."
        )

    existing = get_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists. Please sign in."
        )

    hashed = hash_password(req.password)
    user = create_user(email=email, name=req.name.strip(), password_hash=hashed)
    token = create_access_token({"sub": str(user["id"]), "email": user["email"]})

    return AuthResponse(
        status="success",
        message="Account created successfully",
        token=token,
        user=UserResponse(**user)
    )


@router.post("/auth/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(request: Request, response: Response, req: UserLoginRequest):
    """Authenticates user credentials and issues a JWT session token."""
    email = req.email.strip().lower()
    if email == "demo@clauseclear.com" and not DEMO_LOGIN_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_record = get_user_by_email(email)

    if not user_record or not verify_password(req.password, user_record["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": str(user_record["id"]), "email": user_record["email"]})
    user_profile = {
        "id": user_record["id"],
        "email": user_record["email"],
        "name": user_record["name"],
        "role": user_record["role"],
        "created_at": user_record.get("created_at")
    }

    return AuthResponse(
        status="success",
        message="Signed in successfully",
        token=token,
        user=UserResponse(**user_profile)
    )


@router.post("/auth/demo-login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def demo_login(request: Request, response: Response):
    """Instantly issues a token for the pre-seeded demo user for quick trial."""
    if not DEMO_LOGIN_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo login is disabled.")
    user_record = get_user_by_email("demo@clauseclear.com")
    if not user_record:
        # Fallback create if somehow deleted
        hashed = hash_password("Password123!")
        user_record = create_user("demo@clauseclear.com", "Demo User", hashed, "pro_member")

    token = create_access_token({"sub": str(user_record["id"]), "email": user_record["email"]})
    user_profile = {
        "id": user_record["id"],
        "email": user_record["email"],
        "name": user_record["name"],
        "role": user_record["role"],
        "created_at": user_record.get("created_at")
    }

    return AuthResponse(
        status="success",
        message="Logged in as Demo User",
        token=token,
        user=UserResponse(**user_profile)
    )


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns profile information for the currently authenticated user."""
    return UserResponse(**current_user)


@router.post("/auth/logout")
async def logout():
    """Client logout acknowledgement."""
    return {"status": "success", "message": "Signed out successfully."}


# ================= USER CONTRACT HISTORY ENDPOINTS =================

@router.get("/user/history")
async def get_history(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Retrieves all saved contract analyses for the current user."""
    history = get_user_analyses(user_id=current_user["id"])
    return {
        "count": len(history),
        "history": history
    }


@router.post("/user/history")
async def save_history(
    req: SaveAnalysisHistoryRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Saves a completed contract analysis to the user's personal history."""
    history_id = save_user_analysis(
        user_id=current_user["id"],
        document_title=req.document_title,
        overall_risk_score=req.overall_risk_score,
        total_clauses=req.total_clauses,
        high_risk_count=req.high_risk_count,
        summary_verdict=req.summary_verdict or "",
        analysis_data=req.analysis
    )
    return {
        "status": "success",
        "message": "Analysis saved to history",
        "history_id": history_id
    }


@router.get("/user/history/{history_id}")
async def get_history_detail(
    history_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Retrieves full analysis report for a specific saved contract."""
    record = get_user_analysis_by_id(history_id, user_id=current_user["id"])
    if not record:
        raise HTTPException(status_code=404, detail="Analysis history record not found.")
    return record


@router.delete("/user/history/{history_id}")
async def delete_history_item(
    history_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Deletes a saved contract analysis from user's history."""
    success = delete_user_analysis(history_id, user_id=current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Analysis record not found or already deleted.")
    return {
        "status": "success",
        "message": "Analysis removed from history."
    }
