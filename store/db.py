"""
Capa de persistencia. Único módulo que toca SQLite.

Dedup por fingerprint (hash del contenido ya normalizado), no por
constraint sobre source_url — dos comentarios distintos pueden vivir
en la misma URL.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS mentions (
    id                    TEXT PRIMARY KEY,
    fingerprint           TEXT NOT NULL UNIQUE,
    platform              TEXT NOT NULL,
    source_url            TEXT,
    text                  TEXT NOT NULL,
    author                TEXT,
    published_at          TEXT,
    date_confidence       TEXT NOT NULL,
    country               TEXT,
    likes                 INTEGER DEFAULT 0,
    shares                INTEGER DEFAULT 0,
    comments_count        INTEGER DEFAULT 0,
    sentiment_positive    REAL,
    sentiment_negative    REAL,
    sentiment_neutral     REAL,
    emotion               TEXT,
    is_complaint          INTEGER DEFAULT 0,
    complaint_driver      TEXT,
    classification_status TEXT NOT NULL,
    raw                   TEXT,
    fetched_at            TEXT,
    run_id                TEXT
);

CREATE INDEX IF NOT EXISTS idx_mentions_published ON mentions(published_at);
CREATE INDEX IF NOT EXISTS idx_mentions_platform  ON mentions(platform);
CREATE INDEX IF NOT EXISTS idx_mentions_complaint ON mentions(is_complaint);
CREATE INDEX IF NOT EXISTS idx_mentions_driver    ON mentions(complaint_driver);
CREATE INDEX IF NOT EXISTS idx_mentions_status    ON mentions(classification_status);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    mode            TEXT NOT NULL,
    since           TEXT,
    raw_count       INTEGER DEFAULT 0,
    filtered_count  INTEGER DEFAULT 0,
    inserted_count  INTEGER DEFAULT 0,
    duplicate_count INTEGER DEFAULT 0,
    notes           TEXT
);
"""

_FIELDS = [
    "id", "fingerprint", "platform", "source_url", "text", "author",
    "published_at", "date_confidence", "country", "likes", "shares",
    "comments_count", "sentiment_positive", "sentiment_negative",
    "sentiment_neutral", "emotion", "is_complaint", "complaint_driver",
    "classification_status", "raw", "fetched_at", "run_id",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def fingerprint(platform: str, source_url: str, text: str) -> str:
    """
    Hash del contenido ya normalizado. Se calcula SIEMPRE después de
    normalizar — sobre texto crudo, un espacio distinto crearía un duplicado.
    """
    base = f"{platform}|{source_url or ''}|{(text or '')[:80]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def start_run(conn: sqlite3.Connection, mode: str, since: str | None) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (id, started_at, mode, since) VALUES (?, ?, ?, ?)",
        (run_id, _now(), mode, since),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id, raw_count, filtered_count,
               inserted_count, duplicate_count, notes="") -> None:
    conn.execute(
        """UPDATE runs SET finished_at = ?, raw_count = ?, filtered_count = ?,
                           inserted_count = ?, duplicate_count = ?, notes = ?
           WHERE id = ?""",
        (_now(), raw_count, filtered_count, inserted_count,
         duplicate_count, notes, run_id),
    )
    conn.commit()


def upsert_mentions(conn, mentions: list[dict], run_id: str) -> tuple[int, int]:
    """
    Inserta menciones nuevas. Las que ya existen (mismo fingerprint) se
    ignoran por completo — no se sobrescriben, para preservar run_id y
    fetched_at de la primera vez que se vieron.

    Devuelve (insertadas, duplicadas).
    """
    inserted = 0
    duplicates = 0

    for m in mentions:
        fp = fingerprint(m["platform"], m.get("source_url", ""), m["text"])
        row = {
            **{f: m.get(f) for f in _FIELDS},
            "id": m.get("id") or str(uuid.uuid4()),
            "fingerprint": fp,
            "raw": json.dumps(m.get("raw") or {}, ensure_ascii=False),
            "run_id": run_id,
            "is_complaint": int(bool(m.get("is_complaint", 0))),
            "classification_status": m.get("classification_status", "unclassified"),
        }
        placeholders = ", ".join("?" for _ in _FIELDS)
        cur = conn.execute(
            f"INSERT OR IGNORE INTO mentions ({', '.join(_FIELDS)}) "
            f"VALUES ({placeholders})",
            [row[f] for f in _FIELDS],
        )
        if cur.rowcount:
            inserted += 1
        else:
            duplicates += 1

    conn.commit()
    return inserted, duplicates


def _to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("raw"):
        try:
            d["raw"] = json.loads(d["raw"])
        except (ValueError, TypeError):
            d["raw"] = {}
    return d


def pending_classification(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM mentions WHERE classification_status = 'unclassified'"
    ).fetchall()
    return [_to_dict(r) for r in rows]


def update_classification(conn, mention_id: str, result: dict) -> None:
    conn.execute(
        """UPDATE mentions
           SET sentiment_positive = ?, sentiment_negative = ?,
               sentiment_neutral = ?, emotion = ?, is_complaint = ?,
               complaint_driver = ?, classification_status = 'classified'
           WHERE id = ?""",
        (
            result["sentiment_positive"],
            result["sentiment_negative"],
            result["sentiment_neutral"],
            result["emotion"],
            int(bool(result["is_complaint"])),
            result.get("complaint_driver"),
            mention_id,
        ),
    )
    conn.commit()


def all_mentions(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM mentions ORDER BY published_at DESC").fetchall()
    return [_to_dict(r) for r in rows]
