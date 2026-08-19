"""
Normalizer: valida y limpia el schema unificado.
Filtra menciones sin texto o con texto demasiado corto.
"""
from datetime import datetime, timezone


def normalize(mentions: list[dict]) -> list[dict]:
    """
    Limpia y valida la lista de menciones.
    - Filtra textos vacíos o menores a 10 caracteres
    - Asegura tipos correctos
    - Valida que sentiment sume ~1.0
    """
    clean = []
    for m in mentions:
        text = (m.get("text") or "").strip()
        if len(text) < 10:
            continue

        pos = float(m.get("sentiment_positive", 0.0))
        neg = float(m.get("sentiment_negative", 0.0))
        neu = float(m.get("sentiment_neutral", 1.0))
        total = pos + neg + neu
        if total > 0 and abs(total - 1.0) > 0.05:
            pos, neg, neu = pos/total, neg/total, neu/total

        pub = m.get("published_at")
        if not pub:
            pub = datetime.now(timezone.utc).isoformat()

        clean.append({
            **m,
            "text": text,
            "sentiment_positive": round(pos, 4),
            "sentiment_negative": round(neg, 4),
            "sentiment_neutral":  round(neu, 4),
            "likes":          int(m.get("likes", 0) or 0),
            "shares":         int(m.get("shares", 0) or 0),
            "comments_count": int(m.get("comments_count", 0) or 0),
            "published_at":   pub,
            "is_complaint":   bool(m.get("is_complaint", False)),
        })

    print(f"[Normalizer] {len(clean)}/{len(mentions)} menciones válidas")
    return clean
