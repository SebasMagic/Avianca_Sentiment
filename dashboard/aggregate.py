"""
Agregaciones para el dashboard. Lee la DB y produce el payload JSON.

Sin HTML, sin red. Cuatro reglas que no se negocian, en el orden en que se
aplican:

  - Antes que nada, se descartan las menciones anteriores a
    REPORT_WINDOW_START (config.py). El backfill se pidió con
    --since 2026-04-19, pero el actor de TikTok (clockworks/tiktok-scraper)
    ignoró oldestPostDate y devolvió igual 24 videos de 2023-2025 — reales,
    ya pagados, pero que estiraban el timeline sobre 41 meses con el 98% de
    los datos concentrados en 6. Se aplica UNA sola vez, aquí, a TODO el
    análisis (KPIs, timeline, drivers, sentimiento, emociones, tabla, top
    quejas) para que los números reconcilien entre bloques — no hay
    excepciones por bloque. Las menciones sin published_at (fecha
    desconocida) NO se filtran por esta regla — no hay fecha con la cual
    juzgarlas contra la ventana, y ya tienen su propio tratamiento (la
    regla del timeline, más abajo, y se cuentan en data_quality.unknown_date).
  - Sobre lo que queda dentro de la ventana, las menciones se colapsan por
    (author, text) en "voces" únicas. Una persona real que pega el mismo
    comentario 48 veces (caso medido: alejandra.caicho, 56 filas, 56
    source_url de comentario distintas y reales) es una queja, no 48. Sin
    colapsar, un puñado de spammers reescribe la distribución de drivers:
    con los 1.261 registros crudos de este proyecto, atencion_cliente pasa
    de representar 32,8% de las quejas a solo 26-27% una vez colapsado, y
    "otro" sube de 20,4% a ~26%. El scraper no está mal — cada fila es una
    URL de comentario real — el problema es puramente analítico: contar
    personas, no apariciones. La insistencia del autor no se descarta, se
    reexpone como `repeat_count` en cada voz.
  - El timeline ignora las menciones con date_confidence 'unknown'.
    Meterlas falsearía la serie temporal, que es justo lo que pasó en v1.
  - Los promedios de sentiment ignoran las 'unclassified'. Contarlas
    como neutral inventaría neutralidad que nadie midió.

Todos los bloques (KPIs, timeline, drivers, driver×plataforma, sentiment,
emociones, tabla y top quejas) trabajan sobre las voces ya colapsadas,
dentro de la ventana de reporte.
"""
import collections

from config import REPORT_WINDOW_START
from store import db

PLATFORMS = ["web", "instagram", "tiktok"]


def _engagement(m: dict) -> int:
    return (m.get("likes") or 0) + (m.get("shares") or 0) + (m.get("comments_count") or 0)


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _in_report_window(m: dict) -> bool:
    """
    True si la mención entra en la ventana de reporte (REPORT_WINDOW_START,
    config.py). Sin published_at no hay fecha con la cual evaluarla contra
    la ventana, así que se conserva — el filtro solo excluye lo que
    SABEMOS que es anterior, no lo que no sabemos fechar.
    """
    published_at = m.get("published_at")
    if not published_at:
        return True
    return published_at[:10] >= REPORT_WINDOW_START


def _collapse_voices(mentions: list[dict]) -> list[dict]:
    """
    Agrupa menciones por (author, text) — la misma persona diciendo lo mismo,
    sin importar en qué source_url quedó cada repetición — y devuelve una
    "voz" por grupo.

    De cada grupo se conserva la ocurrencia más antigua por published_at
    (NULL cuenta como la más reciente, para que una fecha ausente no gane
    por accidente el puesto de "primera vez que se vio"), y se le añaden:

      - repeat_count: tamaño del grupo (1 si no se repitió).
      - engagement:   suma de likes+shares+comments_count de TODAS las
                       repeticiones — una queja spammeada sí acumula
                       alcance real, aunque el texto sea el mismo.

    Autores distintos con el mismo texto NO se colapsan: el fingerprint de
    la DB ya incluye el autor exactamente para poder distinguir a dos
    personas distintas citando la misma frase (ver store/db.py). Colapsar
    por texto solo, ignorando el autor, fusionaría voces reales.
    """
    groups: "collections.OrderedDict[tuple, list[dict]]" = collections.OrderedDict()
    for m in mentions:
        key = (m.get("author"), m.get("text"))
        groups.setdefault(key, []).append(m)

    def _sort_key(m: dict):
        # NULL published_at ordena al final tanto para "más antigua" (abajo)
        # como para el orden final descendente (también al final).
        return (m.get("published_at") is None, m.get("published_at") or "")

    voices = []
    for _, group in groups.items():
        oldest = min(group, key=_sort_key)
        voice = dict(oldest)
        voice["repeat_count"] = len(group)
        voice["engagement"] = sum(_engagement(m) for m in group)
        voices.append(voice)

    # Mismo orden que store.db.all_mentions(): más reciente primero.
    voices.sort(key=_sort_key, reverse=True)
    return voices


def _dominant_label(m: dict) -> str:
    """
    Etiqueta de sentiment dominante de UNA mención: la de mayor probabilidad
    entre positive/negative/neutral. Contar por etiqueta dominante (en vez
    de promediar probabilidades) es lo que permite decir "el 52,6% de las
    menciones son positivas" y que esa frase signifique lo que dice —
    promediar probabilidades no sostiene esa lectura (ver docstring de
    build_payload / Cambio 2).

    Desempate (probabilidades exactamente iguales, caso raro pero posible):
    gana negative sobre neutral sobre positive. Un empate no se disuelve
    en la lectura más favorable — se resuelve hacia la señal más accionable
    para un director de servicio, que es la negativa.
    """
    pos = m.get("sentiment_positive") or 0
    neg = m.get("sentiment_negative") or 0
    neu = m.get("sentiment_neutral") or 0
    candidatos = [("negative", neg), ("neutral", neu), ("positive", pos)]
    return max(candidatos, key=lambda par: par[1])[0]


def build_payload(conn) -> dict:
    raw_mentions = db.all_mentions(conn)

    # Ventana de reporte — ver docstring del módulo y config.REPORT_WINDOW_START.
    # Se aplica UNA vez aquí, antes de colapsar voces, para que todo lo que
    # sigue (KPIs, timeline, drivers, sentimiento, emociones, tabla, top
    # quejas) trabaje sobre el mismo conjunto y los números reconcilien.
    windowed_mentions = [m for m in raw_mentions if _in_report_window(m)]
    outside_window = len(raw_mentions) - len(windowed_mentions)

    mentions = _collapse_voices(windowed_mentions)
    collapsed_repeats = len(windowed_mentions) - len(mentions)
    total = len(mentions)

    complaints = [m for m in mentions if m["is_complaint"]]
    classified = [m for m in mentions if m["classification_status"] == "classified"]
    dated = [m for m in mentions if m["date_confidence"] != "unknown" and m["published_at"]]

    # ── Sentiment: conteo por etiqueta dominante (lo que se muestra) y
    # promedio de probabilidades (se conserva por si sirve, no se muestra).
    if classified:
        avg_pos = sum(m["sentiment_positive"] or 0 for m in classified) / len(classified)
        avg_neg = sum(m["sentiment_negative"] or 0 for m in classified) / len(classified)
        avg_neu = sum(m["sentiment_neutral"] or 0 for m in classified) / len(classified)
    else:
        avg_pos = avg_neg = 0.0
        avg_neu = 1.0

    label_counts = collections.Counter(_dominant_label(m) for m in classified)
    n_classified = len(classified)
    sent_counts = {
        "positive": label_counts["positive"],
        "negative": label_counts["negative"],
        "neutral": label_counts["neutral"],
    }
    sent_pct = {k: _pct(v, n_classified) for k, v in sent_counts.items()}

    # ── KPIs
    fechas = sorted(m["published_at"][:10] for m in dated)

    kpis = {
        "total": total,
        "complaints": len(complaints),
        "complaint_rate": _pct(len(complaints), total),
        # Neto sobre etiquetas dominantes, coherente con lo que se muestra
        # en todo el resto del dashboard (ya no promedio de probabilidades).
        "net_sentiment": round(sent_pct["positive"] - sent_pct["negative"], 1),
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
        # pct = peso del driver sobre el total de quejas. Se reutiliza tal
        # cual para la columna "% Total" del heatmap driver×plataforma
        # (bloque 4) — el JS la busca por nombre de driver en vez de
        # recalcularla a mano desde la grilla.
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
        # m["engagement"] ya viene sumado por _collapse_voices (todas las
        # repeticiones de la voz); NO recalcular con _engagement(m) aquí,
        # porque eso volvería a leer solo likes/shares/comments de la
        # ocurrencia más antigua y perdería el alcance de las repeticiones.
        "engagement": m["engagement"],
        "repeat_count": m["repeat_count"],
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
        "unique_voices": total,
        "collapsed_repeats": collapsed_repeats,
        "unknown_date": sum(1 for m in mentions if m["date_confidence"] == "unknown"),
        "unclassified": sum(1 for m in mentions
                            if m["classification_status"] == "unclassified"),
        "filtered_last_run": (last_run["filtered_count"] or 0) if last_run else 0,
        "short_text_last_run": (last_run["short_text_count"] or 0) if last_run else 0,
        "last_run_mode": last_run["mode"] if last_run else None,
        "last_run_at": last_run["finished_at"] if last_run else None,
        "by_platform": dict(por_plataforma),
        "by_month": dict(sorted(cobertura_mes.items())),
        "missing_sources": ["twitter"],
        # Menciones (crudas, antes de colapsar) que quedaron fuera de la
        # ventana de reporte — ver docstring del módulo. Reales, en la DB,
        # pero fuera del análisis.
        "outside_window": outside_window,
        "window_start": REPORT_WINDOW_START,
    }

    return {
        "kpis": kpis,
        "timeline": timeline,
        "drivers": drivers,
        "driver_by_platform": driver_by_platform,
        "driver_trend": driver_trend,
        "sentiment": {
            "counts": sent_counts,
            "pct": sent_pct,
            "classified_count": n_classified,
            # Promedio de probabilidades del clasificador — se conserva por
            # si sirve para otro análisis, pero el dashboard NO lo muestra:
            # "41,3% positivo" como promedio no significa "41,3% de las
            # menciones son positivas", que es lo que cualquiera asume al
            # leerlo (Cambio 2).
            "avg_probabilities": {
                "positive": round(avg_pos * 100, 1),
                "negative": round(avg_neg * 100, 1),
                "neutral": round(avg_neu * 100, 1),
            },
        },
        "emotions": emotions,
        "mentions": filas,
        "top_complaints": top_complaints,
        "data_quality": data_quality,
    }
