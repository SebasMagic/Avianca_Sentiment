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

from config import DB_PATH, DEFAULT_BRAND

# Literal SQL del default de marca, usado tanto en SCHEMA como en las
# migraciones ALTER TABLE (que no admiten `?` para el DEFAULT de una
# columna). Comillas simples escapadas por si algún día DEFAULT_BRAND las
# trae — hoy no las trae, pero mejor no asumirlo en SQL interpolado.
_DEFAULT_BRAND_SQL = DEFAULT_BRAND.replace("'", "''")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS mentions (
    id                    TEXT PRIMARY KEY,
    fingerprint           TEXT NOT NULL UNIQUE,
    brand                 TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}',
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
    saves                 INTEGER,
    views                 INTEGER,
    reach_source          TEXT,
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
    id                TEXT PRIMARY KEY,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    mode              TEXT NOT NULL,
    since             TEXT,
    brand             TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}',
    raw_count         INTEGER DEFAULT 0,
    filtered_count    INTEGER DEFAULT 0,
    inserted_count    INTEGER DEFAULT 0,
    duplicate_count   INTEGER DEFAULT 0,
    short_text_count  INTEGER DEFAULT 0,
    notes             TEXT
);
"""

_FIELDS = [
    "id", "fingerprint", "brand", "platform", "source_url", "text", "author",
    "published_at", "date_confidence", "country", "likes", "shares",
    "comments_count", "saves", "views", "reach_source",
    "sentiment_positive", "sentiment_negative",
    "sentiment_neutral", "emotion", "is_complaint", "complaint_driver",
    "classification_status", "raw", "fetched_at", "run_id",
]

# Columnas de engagement/alcance que update_engagement() tiene permitido tocar.
# Allowlist fija — nunca se interpola un nombre de columna que no venga de aquí,
# así el UPDATE dinámico no puede ejecutar SQL arbitrario a partir del dict que
# le pase el llamador.
_ENGAGEMENT_FIELDS = {"likes", "shares", "comments_count", "saves", "views", "reach_source"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Migraciones aditivas sobre bases YA existentes. Nunca destructivo:
    solo agrega columnas que falten (ALTER TABLE ... ADD COLUMN), nunca
    borra ni recrea tablas. Idempotente: si la columna ya existe, no hace
    nada. data/avianca.db tiene datos reales de scraping pagado — una
    migración destructiva no es aceptable.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "short_text_count" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN short_text_count INTEGER DEFAULT 0")
        conn.commit()
    if "brand" not in cols:
        conn.execute(
            f"ALTER TABLE runs ADD COLUMN brand TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}'"
        )
        conn.commit()

    # saves/views/reach_source (desglose de engagement — ver
    # pipeline/engagement_enrichment.py): sin DEFAULT, quedan NULL en filas
    # viejas. NULL es correcto aquí — "no medido todavía", no "cero".
    mention_cols = {row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()}
    for col, coltype in (("saves", "INTEGER"), ("views", "INTEGER"), ("reach_source", "TEXT")):
        if col not in mention_cols:
            conn.execute(f"ALTER TABLE mentions ADD COLUMN {col} {coltype}")
            conn.commit()

    if "brand" not in mention_cols:
        _add_brand_column_and_refingerprint(conn)

    # Índice sobre brand — se crea acá y no dentro de SCHEMA porque en una
    # DB vieja la columna todavía no existe cuando SCHEMA corre (SCHEMA se
    # ejecuta antes que _migrate); para cuando se llega a esta línea,
    # `brand` ya existe siempre (recién agregada arriba, o ya estaba si la
    # DB es nueva).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_brand ON mentions(brand)")
    conn.commit()


def _add_brand_column_and_refingerprint(conn: sqlite3.Connection) -> None:
    """
    Multi-marca (Tarea 1): agrega `brand` a `mentions` con DEFAULT
    'Avianca' — correcto para las 1.261 filas existentes, todas de
    Avianca — y recalcula el fingerprint de cada una con la nueva firma
    fingerprint(brand, platform, source_url, author, text); antes era
    fingerprint(platform, source_url, author, text), sin marca.

    Recalcular es determinista y no debería colapsar ninguna fila: el
    fingerprint viejo ya era único por combinación
    (platform, source_url, author, text); el nuevo solo le antepone la
    marca (constante 'Avianca' para todas, en esta migración), así que la
    inyectividad se preserva. Aun así se verifica el conteo de filas y de
    fingerprints distintos antes y después, y se aborta la migración
    completa (se lanza, no se traga el error) si no coinciden — sobre
    datos ya pagados, mejor fallar ruidosamente que fusionar en silencio.
    """
    before_count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]

    conn.execute(
        f"ALTER TABLE mentions ADD COLUMN brand TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}'"
    )
    conn.commit()

    rows = conn.execute(
        "SELECT id, platform, source_url, author, text FROM mentions"
    ).fetchall()
    for row in rows:
        mid, platform, source_url, author, text = row[0], row[1], row[2], row[3], row[4]
        new_fp = fingerprint(DEFAULT_BRAND, platform, source_url, author, text)
        conn.execute("UPDATE mentions SET fingerprint = ? WHERE id = ?", (new_fp, mid))
    conn.commit()

    after_count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
    distinct_fp = conn.execute("SELECT COUNT(DISTINCT fingerprint) FROM mentions").fetchone()[0]

    if after_count != before_count:
        raise RuntimeError(
            "Migración de brand/fingerprint abortada: "
            f"filas antes={before_count} después={after_count} — no coinciden."
        )
    if distinct_fp != after_count:
        raise RuntimeError(
            "Migración de brand/fingerprint abortada: "
            f"{after_count} filas pero solo {distinct_fp} fingerprints distintos "
            "— el recálculo habría colapsado filas."
        )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def fingerprint(brand: str, platform: str, source_url: str, author: str | None, text: str) -> str:
    """
    Hash SHA256 del contenido completo (brand|platform|url|author|text íntegro).

    Se hashea el TEXTO COMPLETO sin truncar para evitar colisiones falsas.
    Dos comentarios genuinamente distintos que comparten un prefijo largo
    pueden coexistir en la misma URL — el dedup por fingerprint debe
    distinguirlos correctamente.

    El autor está incluido en el fingerprint para discriminar personas distintas:
    si dos autores distintos escriben lo mismo en la misma URL, son dos menciones
    diferentes. Esto evita falsos positivos en redes donde la URL es constante
    (ej. Instagram scrape usa una URL genérica). Un mismo autor repitiendo texto
    idéntico SÍ se deduplica correctamente (re-scrape).

    La marca también está incluida: dos marcas pueden tener menciones
    legítimamente idénticas (una nota de prensa que nombra a ambas) y no
    deben deduplicarse entre sí — cada marca vive en su propio espacio de
    fingerprints.

    Diseño: un duplicado falso es una fila auditable; una fusión falsa
    es pérdida irrecuperable de datos. La asimetría decide: hashea completo.
    """
    base = f"{brand}|{platform}|{source_url or ''}|{author or ''}|{text or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def start_run(conn: sqlite3.Connection, mode: str, since: str | None,
              brand: str = DEFAULT_BRAND) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (id, started_at, mode, since, brand) VALUES (?, ?, ?, ?, ?)",
        (run_id, _now(), mode, since, brand),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id, raw_count, filtered_count,
               inserted_count, duplicate_count, notes="",
               short_text_count=0) -> None:
    conn.execute(
        """UPDATE runs SET finished_at = ?, raw_count = ?, filtered_count = ?,
                           inserted_count = ?, duplicate_count = ?,
                           short_text_count = ?, notes = ?
           WHERE id = ?""",
        (_now(), raw_count, filtered_count, inserted_count,
         duplicate_count, short_text_count, notes, run_id),
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
        brand = m.get("brand") or DEFAULT_BRAND
        fp = fingerprint(brand, m["platform"], m.get("source_url", ""), m.get("author"), m["text"])
        row = {
            **{f: m.get(f) for f in _FIELDS},
            "id": m.get("id") or str(uuid.uuid4()),
            "brand": brand,
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


def pending_classification(conn, brand: str | None = None) -> list[dict]:
    """
    Menciones sin clasificar. `brand` es opcional: sin él, devuelve las
    pendientes de todas las marcas (comportamiento histórico); pasándolo,
    lo acota a una sola — así una corrida de LATAM no reintenta clasificar
    con el prompt de LATAM las pendientes que dejó una corrida de Avianca.
    """
    if brand is None:
        rows = conn.execute(
            "SELECT * FROM mentions WHERE classification_status = 'unclassified'"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM mentions WHERE classification_status = 'unclassified' AND brand = ?",
            (brand,),
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


def update_engagement(conn, mention_id: str, fields: dict) -> None:
    """
    Actualiza columnas de engagement/alcance (likes, shares, comments_count,
    saves, views, reach_source) de una mención YA existente. No inserta filas,
    no toca clasificación ni ningún otro campo — usado por el enriquecimiento
    retroactivo (pipeline/engagement_enrichment.py, backfill de alcance de
    Instagram) para corregir esas columnas desde datos ya pagados.

    `fields` puede traer solo un subconjunto (p.ej. solo views+reach_source);
    las claves fuera de _ENGAGEMENT_FIELDS se ignoran en vez de fallar, para
    que el llamador pueda pasar un dict con más contexto sin filtrar antes.
    Solo se actualizan columnas de la allowlist fija _ENGAGEMENT_FIELDS —
    nunca se interpola un nombre de columna ajeno al dict.
    """
    cols = [c for c in fields if c in _ENGAGEMENT_FIELDS]
    if not cols:
        return
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(
        f"UPDATE mentions SET {set_clause} WHERE id = ?",
        [fields[c] for c in cols] + [mention_id],
    )
    conn.commit()


def all_mentions(conn, brand: str | None = None) -> list[dict]:
    """
    Todas las menciones, o solo las de `brand` si se pasa uno — el
    dashboard y el export de Excel quieren la vista de una sola marca a
    la vez, sin dejar de poder pedir todo junto cuando haga falta.
    """
    if brand is None:
        rows = conn.execute("SELECT * FROM mentions ORDER BY published_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM mentions WHERE brand = ? ORDER BY published_at DESC", (brand,)
        ).fetchall()
    return [_to_dict(r) for r in rows]


def last_completed_run_started_at(conn) -> str | None:
    """
    `started_at` (ISO 8601) de la última corrida que TERMINÓ
    (finished_at IS NOT NULL), o None si no hay ninguna.

    Se usa para calcular el `since` incremental de la corrida `weekly`:
    apoyarse en cuándo arrancó la última corrida real (en vez de un
    rolling fijo de 7 días) evita abrir huecos si una semana se salta.
    Corridas en curso o abortadas (sin finished_at) no cuentan.
    """
    row = conn.execute(
        "SELECT started_at FROM runs WHERE finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row["started_at"] if row else None
