from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DELTAWATCH_DATA_DIR", BASE_DIR / "data")).resolve()
DB_PATH = Path(os.getenv("DELTAWATCH_DB_PATH", DATA_DIR / "deltawatch.sqlite3")).resolve()
ARTIFACTS_DIR = Path(os.getenv("DELTAWATCH_ARTIFACTS_DIR", DATA_DIR / "artifacts")).resolve()
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DELTAWATCH_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
CHECK_TIMEOUT_SECONDS = int(os.getenv("DELTAWATCH_CHECK_TIMEOUT_SECONDS", "25"))
WORKER_COUNT = max(1, int(os.getenv("DELTAWATCH_WORKERS", "3")))
SCHEDULER_ENABLED = os.getenv("DELTAWATCH_ENABLE_SCHEDULER", "true").lower() in {
    "1", "true", "yes", "on"
}
PUBLIC_APP_URL = os.getenv("DELTAWATCH_PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
SMTP_HOST = os.getenv("DELTAWATCH_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("DELTAWATCH_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("DELTAWATCH_SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("DELTAWATCH_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("DELTAWATCH_SMTP_FROM", SMTP_USERNAME or "")
SMTP_USE_TLS = os.getenv("DELTAWATCH_SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
USER_AGENT = os.getenv(
    "DELTAWATCH_USER_AGENT",
    "DeltaWatchBot/1.0 (+local website change monitoring; respectful rate limits)",
)
MAX_CAPTURE_TEXT_CHARS = int(os.getenv("DELTAWATCH_MAX_CAPTURE_TEXT_CHARS", "500000"))
MAX_SCREENSHOT_PIXELS = 16_000_000


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / "screenshots").mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / "diffs").mkdir(parents=True, exist_ok=True)
