"""
Agregaciones para el dashboard. Lee la DB y produce el payload JSON.

Sin HTML, sin red. Dos reglas de exclusión que no se negocian:
  - El timeline ignora las menciones con date_confidence 'unknown'.
    Meterlas falsearía la serie temporal, que es justo lo que pasó en v1.
  - Los promedios de sentiment ignoran las 'unclassified'. Contarlas
    como neutral inventaría neutralidad que nadie midió.
"""
import collections

from store import db

PLATFORMS = ["web", "instagram", "tiktok"]


def _engagement(m: dict) -> int:
    return (m.get("likes") or 0) + (m.get("shares") or 0) + (m.get("comments_count") or 0)


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def build_payload(conn) -> dict:
    mentions = db.all_mentions(conn)
    total = len(mentions)

    complaints = [m for m in mentions if m["is_complaint"]]
    classified = [m for m in mentions if m["classification_status"] == "classified"]
    dated = [m for m in mentions if m["date_confidence"] != "unknown" and m["published_at"]]

    # ── KPIs
    if classified:
        pos = sum(m["sentiment_positive"] or 0 for m in classified) / len(classified)
        neg = sum(m["sentiment_negative"] or 0 for m in classified) / len(classified)
        neu = sum(m["sentiment_neutral"] or 0 for m in classified) / len(classified)
    else:
        pos = neg = 0.0
        neu = 1.0

    fechas = sorted(m["published_at"][:10] for m in dated)

    kpis = {
        "total": total,
        "complaints": len(complaints),
        "complaint_rate": _pct(len(complaints), total),
        "net_sentiment": round((pos - neg) * 100, 1),
        "date_from": fechas[0] if fechas else None,
        "date_to": fechas[-1] if fechas else None,
        "sources": len({m["platform"] for m in mentions}),
    }

    # ── Timeline (solo fechas confiables)
    por_dia = collections.defaultdict(lambda: collections.Counter())
    sent_dia = collections.defaultdict(list)
    for m in dated:
        dia = m["published_at"][:10]
        por_dia[dia][m["platform"]] += 1
        if m["classification_status"] == "classified":
            sent_dia[dia].append((m["sentiment_positive"] or 0) - (m["sentiment_negative"] or 0))

    timeline = []
    for dia in sorted(por_dia):
        muestras = sent_dia.get(dia, [])
        timeline.append({
            "date": dia,
            "counts": {p: por_dia[dia].get(p, 0) for p in PLATFORMS},
            "net_sentiment": round(sum(muestras) / len(muestras) * 100, 1) if muestras else None,
        })

    # ── Drivers
    conteo_driver = collections.Counter(
        m["complaint_driver"] for m in complaints if m["complaint_driver"]
    )
    drivers = [
        {"driver": d, "count": c, "pct": _pct(c, len(complaints))}
        for d, c in conteo_driver.most_common()
    ]

    # ── Driver × plataforma
    cruce = collections.Counter(
        (m["complaint_driver"], m["platform"])
        for m in complaints if m["complaint_driver"]
    )
    driver_by_platform = [
        {"driver": d, "platform": p, "count": c}
        for (d, p), c in sorted(cruce.items())
    ]

    # ── Drivers por mes (tendencia)
    por_mes = collections.Counter(
        (m["published_at"][:7], m["complaint_driver"])
        for m in complaints
        if m["complaint_driver"] and m["published_at"] and m["date_confidence"] != "unknown"
    )
    driver_trend = [
        {"month": mes, "driver": d, "count": c}
        for (mes, d), c in sorted(por_mes.items())
    ]

    # ── Emociones
    emotions = dict(collections.Counter(
        m["emotion"] for m in classified if m["emotion"]
    ))

    # ── Tabla y top quejas
    filas = [{
        "id": m["id"],
        "platform": m["platform"],
        "text": m["text"],
        "author": m["author"],
        "published_at": m["published_at"],
        "date_confidence": m["date_confidence"],
        "source_url": m["source_url"],
        "is_complaint": bool(m["is_complaint"]),
        "complaint_driver": m["complaint_driver"],
        "emotion": m["emotion"],
        "sentiment_negative": m["sentiment_negative"],
        "engagement": _engagement(m),
    } for m in mentions]

    top_complaints = sorted(
        [f for f in filas if f["is_complaint"]],
        key=lambda f: f["engagement"],
        reverse=True,
    )[:20]

    # ── Calidad de datos
    por_plataforma = collections.Counter(m["platform"] for m in mentions)
    cobertura_mes = collections.Counter(m["published_at"][:7] for m in dated)

    # filtered_count se recalcula sobre el archivo/lote completo en cada corrida
    # de seed/scraping, aunque upsert_mentions deduplique lo ya visto. No hay
    # forma de deduplicar los descartes entre corridas (no se persisten), así
    # que un acumulado histórico sería una cifra inventada. Reportamos solo la
    # última corrida que terminó, etiquetada como tal — no un total.
    last_run = conn.execute(
        "SELECT * FROM runs WHERE finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    last_run = dict(last_run) if last_run else None

    data_quality = {
        "total": total,
        "unknown_date": sum(1 for m in mentions if m["date_confidence"] == "unknown"),
        "unclassified": sum(1 for m in mentions
                            if m["classification_status"] == "unclassified"),
        "filtered_last_run": (last_run["filtered_count"] or 0) if last_run else 0,
        "last_run_mode": last_run["mode"] if last_run else None,
        "last_run_at": last_run["finished_at"] if last_run else None,
        "by_platform": dict(por_plataforma),
        "by_month": dict(sorted(cobertura_mes.items())),
        "missing_sources": ["twitter"],
    }

    return {
        "kpis": kpis,
        "timeline": timeline,
        "drivers": drivers,
        "driver_by_platform": driver_by_platform,
        "driver_trend": driver_trend,
        "sentiment": {
            "positive": round(pos * 100, 1),
            "negative": round(neg * 100, 1),
            "neutral": round(neu * 100, 1),
            "classified_count": len(classified),
        },
        "emotions": emotions,
        "mentions": filas,
        "top_complaints": top_complaints,
        "data_quality": data_quality,
    }
