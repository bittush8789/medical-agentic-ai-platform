import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG_FILE = LOGS_DIR / "audit.log"

# Setup Dedicated Audit Logger
audit_logger = logging.getLogger("medguide_audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False  # Avoid duplicating in standard stdout

# 10 MB per file, keep up to 5 rotation backups
if not audit_logger.handlers:
    file_handler = RotatingFileHandler(
        AUDIT_LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    # Plain message format as we write pre-formatted JSON strings
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(file_handler)

# Database table initialization
DB_PATH = ROOT / "medical_memory.db"

def init_audit_db():
    try:
        with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    conversation_id TEXT,
                    model TEXT,
                    status TEXT,
                    latency_ms REAL,
                    tools_invoked TEXT,
                    client_ip TEXT,
                    details TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_conv ON audit_logs(conversation_id)")
            conn.commit()
    except Exception as exc:
        print(f"Audit DB init warning: {exc}")

# Initialize table on import
init_audit_db()


# Emergency triage indicators for audit alerts
EMERGENCY_KEYWORDS = (
    "chest pain", "heart attack", "stroke", "trouble breathing",
    "shortness of breath", "severe bleeding", "unconscious",
    "fainted", "suicidal", "suicide", "overdose", "anaphylaxis"
)

def detect_triage_alert(text: str | None) -> list[str]:
    """Detect presence of critical medical emergency indicators for audit tracking."""
    if not text:
        return []
    text_lower = text.lower()
    return [kw for kw in EMERGENCY_KEYWORDS if kw in text_lower]


def log_audit_event(
    event_type: str,
    conversation_id: str | None = None,
    model: str | None = None,
    status: str = "SUCCESS",
    latency_ms: float | None = None,
    tools_invoked: list[str] | None = None,
    client_ip: str | None = None,
    details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Log a structured audit event to both the rotating audit JSON log file
    and the persistent SQLite audit table.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    record = {
        "timestamp": now_utc,
        "event_type": event_type,
        "conversation_id": conversation_id or "anonymous",
        "model": model or "none",
        "status": status,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "tools_invoked": tools_invoked or [],
        "client_ip": client_ip or "local",
        "details": details or {}
    }

    # 1. Log as structured JSON line in audit.log
    try:
        audit_logger.info(json.dumps(record, ensure_ascii=False))
    except Exception as exc:
        print(f"Audit file write error: {exc}")

    # 2. Record in SQLite audit_logs table
    try:
        with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
            conn.execute(
                """
                INSERT INTO audit_logs 
                (timestamp, event_type, conversation_id, model, status, latency_ms, tools_invoked, client_ip, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_utc,
                    event_type,
                    conversation_id,
                    model,
                    status,
                    latency_ms,
                    json.dumps(tools_invoked or []),
                    client_ip,
                    json.dumps(details or {}, ensure_ascii=False)
                )
            )
            conn.commit()
    except Exception as exc:
        print(f"Audit DB insert error: {exc}")

    return record


def get_recent_audit_logs(limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
    """Retrieve recent audit events for observability and audit review."""
    query = "SELECT timestamp, event_type, conversation_id, model, status, latency_ms, tools_invoked, client_ip, details FROM audit_logs"
    params: list[Any] = []
    
    if event_type:
        query += " WHERE event_type = ?"
        params.append(event_type)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    results = []
    try:
        with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                try:
                    tools = json.loads(row["tools_invoked"]) if row["tools_invoked"] else []
                except Exception:
                    tools = []
                try:
                    details = json.loads(row["details"]) if row["details"] else {}
                except Exception:
                    details = {}

                results.append({
                    "timestamp": row["timestamp"],
                    "event_type": row["event_type"],
                    "conversation_id": row["conversation_id"],
                    "model": row["model"],
                    "status": row["status"],
                    "latency_ms": row["latency_ms"],
                    "tools_invoked": tools,
                    "client_ip": row["client_ip"],
                    "details": details
                })
    except Exception as exc:
        print(f"Failed to read audit logs: {exc}")

    return results
