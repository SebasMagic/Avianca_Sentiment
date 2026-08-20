"""
Normalizer: valida y limpia el schema unificado.

Regla dura: si no hay fecha de publicación, published_at queda None y
date_confidence queda 'unknown'. NUNCA se sustituye por fetched_at —
eso fue lo que hizo que las 100 menciones web del v1 dijeran todas
la misma fecha.
"""

MIN_TEXT_LENGTH = 10


def normalize(mentions: list[dict]) -> list[dict]:
    clean = []

    for m in mentions:
        text = (m.get("text") or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            continue

        pos = float(m.get("sentiment_positive") or 0.0)
        neg = float(m.get("sentiment_negative") or 0.0)
        neu = float(m.get("sentiment_neutral") or 0.0)
        total = pos + neg + neu
        if total > 0 and abs(total - 1.0) > 0.05:
            pos, neg, neu = pos / total, neg / total, neu / total

        published = m.get("published_at") or None
        confidence = m.get("date_confidence")
        if not confidence:
            confidence = "exact" if published else "unknown"
        if not published:
            confidence = "unknown"

        clean.append({
            **m,
            "text": text,
            "published_at": published,
            "date_confidence": confidence,
            "sentiment_positive": round(pos, 4),
            "sentiment_negative": round(neg, 4),
            "sentiment_neutral": round(neu, 4),
            "likes": int(m.get("likes") or 0),
            "shares": int(m.get("shares") or 0),
            "comments_count": int(m.get("comments_count") or 0),
            "is_complaint": bool(m.get("is_complaint", False)),
        })

    print(f"[Normalizer] {len(clean)}/{len(mentions)} menciones válidas")
    return clean
