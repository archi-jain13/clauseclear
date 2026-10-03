import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
FRONTEND_DIR = BASE_DIR / "frontend"
KNOWLEDGE_BASE_DIR = BACKEND_DIR / "knowledge_base"
EVALUATION_DIR = BACKEND_DIR / "evaluation"
SAMPLES_DIR = BACKEND_DIR / "samples"
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data"))
LANCEDB_DIR = Path(os.getenv("LANCEDB_DIR", DATA_DIR / "lancedb"))
LANCEDB_TABLE = "clauses"
DATABASE_PATH = DATA_DIR / "clauseclear.db"

# Load local configuration before reading settings. Production platforms should
# inject secrets through their environment or secret manager.
load_dotenv(BASE_DIR / ".env")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_DEVELOPMENT = ENVIRONMENT == "development"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in ("true", "1", "yes")


# Auth configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if ENVIRONMENT == "production" and len(JWT_SECRET_KEY) < 32:
    raise RuntimeError("Production requires JWT_SECRET_KEY with at least 32 characters.")
if not JWT_SECRET_KEY:
    JWT_SECRET_KEY = "development-only-not-for-production"

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = int(os.getenv("JWT_EXPIRATION_DAYS", "7"))
DEMO_LOGIN_ENABLED = IS_DEVELOPMENT and _env_bool("DEMO_LOGIN_ENABLED", True)
RUNTIME_API_KEY_UPDATES_ENABLED = IS_DEVELOPMENT and _env_bool("RUNTIME_API_KEY_UPDATES_ENABLED", True)

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Server settings
HOST = os.getenv("HOST", "127.0.0.1" if IS_DEVELOPMENT else "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))
DEBUG = _env_bool("DEBUG", IS_DEVELOPMENT)
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))
if MAX_REQUEST_BYTES <= 0:
    raise RuntimeError("MAX_REQUEST_BYTES must be a positive integer.")
RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000" if IS_DEVELOPMENT else ""
    ).split(",")
    if origin.strip()
]

# Model configuration
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "groq")  # options: gemini, groq, local, openai, anthropic
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_EMBEDDING_MODEL = "text-embedding-004"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")  # fast & capable Groq model
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

def set_runtime_api_key(key: str):
    global GEMINI_API_KEY
    GEMINI_API_KEY = key
    os.environ["GEMINI_API_KEY"] = key

def set_groq_api_key(key: str):
    global GROQ_API_KEY
    GROQ_API_KEY = key
    os.environ["GROQ_API_KEY"] = key
