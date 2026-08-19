"""
Importa el Excel del pipeline v1 al schema v2.

Rescata el histórico ya pagado (sobre todo TikTok, que tiene 4 meses reales)
sin volver a gastar en scraping.

Todas las filas entran como 'unclassified' a propósito:
  - Las web nunca fueron analizadas (DataForSEO devolvió sentiment vacío).
  - Las sociales no tienen complaint_driver porque el campo no existía en v1.
Reclasificar todo es lo único que deja el dataset homogéneo.
"""
import collections
import uuid

import openpyxl

from pipeline.relevance import is_relevant
from store import db

COLUMN_MAP = {
    "Plataforma": "platform",
    "Texto": "text",
    "Autor": "author",
    "Fecha publicación": "published_at",
    "URL": "source_url",
    "Likes": "likes",
    "Shares": "shares",
    "Comentarios": "comments_count",
    "Emoción": "emotion",
    "Extraído en": "fetched_at",
}


def _num(value, cast=int):
    try:
        return cast(value or 0)
    except (TypeError, ValueError):
        return cast(0)


def read_excel(path: str) -> list[dict]:
    ws = openpyxl.load_workbook(path).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = list(rows[0])
    index = {h: n for n, h in enumerate(headers)}
    out = []

    for row in rows[1:]:
        get = lambda col: row[index[col]] if col in index else None

        text = (get("Texto") or "").strip()
        if not text:
            continue

        published = get("Fecha publicación")
        fetched = get("Extraído en")
        published = str(published) if published else None
        fetched = str(fetched) if fetched else None

        # La fecha web del v1 es un fallback a fetched_at: no es una fecha real.
        if published and fetched and published == fetched:
            published, confidence = None, "unknown"
        elif published:
            confidence = "exact"
        else:
            confidence = "unknown"

        out.append({
            "id": str(uuid.uuid4()),
            "platform": get("Plataforma"),
            "source_url": get("URL") or "",
            "text": text,
            "author": get("Autor"),
            "published_at": published,
            "date_confidence": confidence,
            "country": "CO",
            "likes": _num(get("Likes")),
            "shares": _num(get("Shares")),
            "comments_count": _num(get("Comentarios")),
            "sentiment_positive": None,
            "sentiment_negative": None,
            "sentiment_neutral": None,
            "emotion": None,
            "is_complaint": 0,
            "complaint_driver": None,
            "classification_status": "unclassified",
            "raw": {"origen": "seed_excel_v1"},
            "fetched_at": fetched,
        })

    return out


def seed(path: str, conn) -> dict:
    filas = read_excel(path)
    run_id = db.start_run(conn, "seed", None)

    razones = collections.Counter()
    keep = []
    for m in filas:
        ok, razon = is_relevant(m)
        if ok:
            keep.append(m)
        else:
            razones[razon] += 1

    inserted, duplicates = db.upsert_mentions(conn, keep, run_id)

    db.finish_run(
        conn, run_id,
        raw_count=len(filas),
        filtered_count=len(filas) - len(keep),
        inserted_count=inserted,
        duplicate_count=duplicates,
        notes=f"seed desde {path}",
    )

    return {
        "raw": len(filas),
        "filtered": len(filas) - len(keep),
        "inserted": inserted,
        "duplicates": duplicates,
        "filter_reasons": dict(razones),
    }
