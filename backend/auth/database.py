import sqlite3
import json
from typing import Optional, List, Dict, Any
try:
    from backend.config import DATA_DIR, DATABASE_PATH, DEMO_LOGIN_ENABLED
except ImportError:
    try:
        from ..config import DATA_DIR, DATABASE_PATH, DEMO_LOGIN_ENABLED
    except ImportError:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from backend.config import DATA_DIR, DATABASE_PATH, DEMO_LOGIN_ENABLED


def get_db_connection() -> sqlite3.Connection:
    """Creates a connection to the SQLite database with row dictionary mapping."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initializes the database schema and seeds initial records if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # User Contract Analysis History table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            document_title TEXT NOT NULL,
            overall_risk_score INTEGER NOT NULL,
            total_clauses INTEGER NOT NULL,
            high_risk_count INTEGER NOT NULL,
            summary_verdict TEXT,
            analysis_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    # Index for fast user history lookup
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_analyses_user_id 
        ON user_analyses (user_id, created_at DESC)
    """)

    conn.commit()

    # Seed demo user only for local development.
    if DEMO_LOGIN_ENABLED:
        cursor.execute("SELECT id FROM users WHERE email = ?", ("demo@clauseclear.com",))
        demo_user_exists = cursor.fetchone()
    else:
        demo_user_exists = True

    if not demo_user_exists:
        try:
            from backend.auth.security import hash_password
        except ImportError:
            from .security import hash_password
        demo_pass_hash = hash_password("Password123!")
        cursor.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
            ("demo@clauseclear.com", "Demo User", demo_pass_hash, "pro_member")
        )
        conn.commit()

    conn.close()


def create_user(email: str, name: str, password_hash: str, role: str = "user") -> Dict[str, Any]:
    """Creates a new user record and returns the user dict without password hash."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
        (email.strip().lower(), name.strip(), password_hash, role)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return get_user_by_id(user_id)


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieves a user by email, including the password hash for authentication."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip().lower(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a user by ID, excluding sensitive fields."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, role, created_at FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def save_user_analysis(
    user_id: int,
    document_title: str,
    overall_risk_score: int,
    total_clauses: int,
    high_risk_count: int,
    summary_verdict: str,
    analysis_data: Dict[str, Any]
) -> int:
    """Saves a contract analysis into the user's history."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO user_analyses (
            user_id, document_title, overall_risk_score, total_clauses, high_risk_count, summary_verdict, analysis_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            document_title,
            overall_risk_score,
            total_clauses,
            high_risk_count,
            summary_verdict,
            json.dumps(analysis_data)
        )
    )
    history_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return history_id


def get_user_analyses(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves list of past analysis summaries for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, document_title, overall_risk_score, total_clauses, high_risk_count, summary_verdict, created_at
        FROM user_analyses
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_analysis_by_id(analysis_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves the full analysis data for a specific historical record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, document_title, overall_risk_score, total_clauses, high_risk_count, summary_verdict, analysis_json, created_at
        FROM user_analyses
        WHERE id = ? AND user_id = ?
        """,
        (analysis_id, user_id)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        data = dict(row)
        data["analysis"] = json.loads(data["analysis_json"])
        del data["analysis_json"]
        return data
    return None


def delete_user_analysis(analysis_id: int, user_id: int) -> bool:
    """Deletes a saved analysis report from the user's history."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_analyses WHERE id = ? AND user_id = ?", (analysis_id, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0
