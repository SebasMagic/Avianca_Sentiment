"""
Tarea 3 de prensa/reseñas: la prensa NUNCA suma a la tasa de quejas del
KPI principal (bloque 1) ni a ningún bloque derivado de `mentions`
(timeline, drivers, sentiment, emociones, tabla, top quejas) — vive por
su cuenta en payload["press"]. Las reseñas SÍ suman a esos bloques, con
su estrella promedio expuesta aparte en payload["reviews"]. Ver el
docstring de dashboard/aggregate.py (sección "Prensa y reseñas") para la
regla completa.
"""
from dashboard import aggregate
from store import db


def _m(idx, **kw):
    base = {
        "id": f"m-{idx}",
        "platform": "tiktok",
        "source_url": f"https://x.com/{idx}",
        "text": f"Avianca comentario numero {idx} sobre el servicio",
        "author": "user",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10, "shares": 1, "comments_count": 2,
        "sentiment_positive": 0.1, "sentiment_negative": 0.8,
        "sentiment_neutral": 0.1, "emotion": "anger",
        "is_complaint": 1, "complaint_driver": "equipaje",
        "classification_status": "classified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _prensa(idx, **kw):
    base = _m(
        idx,
        platform="prensa",
        text=f"Avianca es noticia número {idx}",
        author="eltiempo.com",
        is_complaint=0,
        complaint_driver=None,
        sentiment_positive=0.1, sentiment_negative=0.1, sentiment_neutral=0.8,
        emotion="neutral",
    )
    base.update(kw)
    return base


def _resena(idx, rating=1, **kw):
    base = _m(
        idx,
        platform="resena",
        source_url=f"https://www.trustpilot.com/reviews/{idx}",
        text=f"Reseña número {idx}: pésimo servicio, nunca devolvieron mi dinero",
        author=f"reviewer{idx}",
    )
    base["rating"] = rating
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


# ── Prensa nunca suma a kpis/complaints/timeline/tabla ─────────────────

def test_prensa_no_suma_a_kpis_ni_a_complaints(tmp_db):
    _seed(tmp_db, [
        _m(1),  # queja real de tiktok
        _prensa(2, is_complaint=1, complaint_driver="cancelacion"),  # nota "queja" según el LLM
    ])
    p = aggregate.build_payload(tmp_db)

    assert p["kpis"]["total"] == 1
    assert p["kpis"]["complaints"] == 1
    assert p["kpis"]["complaint_rate"] == 100.0
    assert p["press"]["total"] == 1


def test_prensa_no_aparece_en_mentions_ni_top_quejas(tmp_db):
    _seed(tmp_db, [_prensa(1, is_complaint=1, complaint_driver="cancelacion")])
    p = aggregate.build_payload(tmp_db)

    assert p["mentions"] == []
    assert p["top_complaints"]["with_own_reach"] == []
    assert p["top_complaints"]["without_own_reach"] == []


def test_prensa_no_aparece_en_timeline_pero_resena_si(tmp_db):
    _seed(tmp_db, [
        _prensa(1),
        _resena(2),
    ])
    p = aggregate.build_payload(tmp_db)

    punto = p["timeline"][0]
    assert "prensa" not in punto["counts"]
    assert punto["counts"]["resena"] == 1


def test_prensa_no_afecta_drivers_ni_driver_by_platform(tmp_db):
    _seed(tmp_db, [
        _m(1, complaint_driver="equipaje"),
        _prensa(2, is_complaint=1, complaint_driver="equipaje"),
    ])
    p = aggregate.build_payload(tmp_db)

    # El driver "equipaje" solo debe contar la queja real (tiktok) — la
    # nota de prensa, aunque el LLM la haya marcado is_complaint, no se
    # mezcla en este conteo.
    equipaje = next(d for d in p["drivers"] if d["driver"] == "equipaje")
    assert equipaje["count"] == 1
    assert all(row["platform"] != "prensa" for row in p["driver_by_platform"])


# ── Reseñas SÍ suman a la conversación de usuarios ──────────────────────

def test_resena_suma_a_kpis_y_complaint_rate(tmp_db):
    _seed(tmp_db, [_resena(1, rating=1)])
    p = aggregate.build_payload(tmp_db)

    assert p["kpis"]["total"] == 1
    assert p["kpis"]["complaints"] == 1
    assert p["kpis"]["complaint_rate"] == 100.0


def test_resena_aparece_en_tabla_con_rating(tmp_db):
    _seed(tmp_db, [_resena(1, rating=2)])
    p = aggregate.build_payload(tmp_db)

    assert len(p["mentions"]) == 1
    assert p["mentions"][0]["platform"] == "resena"
    assert p["mentions"][0]["rating"] == 2


def test_rating_es_none_para_no_resenas(tmp_db):
    _seed(tmp_db, [_m(1)])
    p = aggregate.build_payload(tmp_db)
    assert p["mentions"][0]["rating"] is None


# ── payload["reviews"]: estrella promedio ───────────────────────────────

def test_reviews_avg_rating(tmp_db):
    _seed(tmp_db, [_resena(1, rating=1), _resena(2, rating=3), _resena(3, rating=5)])
    p = aggregate.build_payload(tmp_db, brand="Avianca")

    assert p["reviews"]["total"] == 3
    assert p["reviews"]["rated_count"] == 3
    assert p["reviews"]["avg_rating"] == 3.0
    assert p["reviews"]["rating_counts"] == {1: 1, 3: 1, 5: 1}
    assert p["reviews"]["domain"] == "avianca.com"


def test_reviews_sin_datos_no_revienta(tmp_db):
    p = aggregate.build_payload(tmp_db, brand="Avianca")
    assert p["reviews"]["total"] == 0
    assert p["reviews"]["avg_rating"] is None
    assert p["reviews"]["rating_counts"] == {}


def test_reviews_domain_es_especifico_por_marca(tmp_db):
    p_avianca = aggregate.build_payload(tmp_db, brand="Avianca")
    p_latam = aggregate.build_payload(tmp_db, brand="LATAM")
    assert p_avianca["reviews"]["domain"] == "avianca.com"
    assert p_latam["reviews"]["domain"] == "latamairlines.com"


def test_reviews_domain_es_none_en_vista_combinada(tmp_db):
    p = aggregate.build_payload(tmp_db, brand=None)
    assert p["reviews"]["domain"] is None


# ── payload["press"]: por derecho propio ────────────────────────────────

def test_press_sentiment_y_medios(tmp_db):
    _seed(tmp_db, [
        _prensa(1, author="eltiempo.com", sentiment_negative=0.9,
                sentiment_positive=0.05, sentiment_neutral=0.05, emotion="anger"),
        _prensa(2, author="eltiempo.com", sentiment_negative=0.9,
                sentiment_positive=0.05, sentiment_neutral=0.05, emotion="anger"),
        _prensa(3, author="semana.com", sentiment_positive=0.8,
                sentiment_negative=0.1, sentiment_neutral=0.1, emotion="happiness"),
    ])
    p = aggregate.build_payload(tmp_db)

    assert p["press"]["total"] == 3
    assert p["press"]["sentiment"]["counts"]["negative"] == 2
    assert p["press"]["sentiment"]["counts"]["positive"] == 1

    outlets = {o["domain"]: o["count"] for o in p["press"]["outlets"]}
    assert outlets == {"eltiempo.com": 2, "semana.com": 1}


def test_press_topics_solo_de_notas_marcadas_como_queja(tmp_db):
    _seed(tmp_db, [
        _prensa(1, is_complaint=1, complaint_driver="cancelacion"),
        _prensa(2, is_complaint=0, complaint_driver=None),  # nota positiva, sin tema
    ])
    p = aggregate.build_payload(tmp_db)

    assert p["press"]["topics"] == [{"driver": "cancelacion", "count": 1, "pct": 50.0}]


def test_press_headlines_recientes_primero(tmp_db):
    _seed(tmp_db, [
        _prensa(1, published_at="2026-05-01T00:00:00+00:00", text="Nota vieja"),
        _prensa(2, published_at="2026-05-03T00:00:00+00:00", text="Nota nueva"),
    ])
    p = aggregate.build_payload(tmp_db)

    titulos = [h["title"] for h in p["press"]["headlines"]]
    assert titulos == ["Nota nueva", "Nota vieja"]


def test_press_respeta_ventana_de_reporte(tmp_db):
    _seed(tmp_db, [_prensa(1, published_at="2025-01-01T00:00:00+00:00")])
    p = aggregate.build_payload(tmp_db)
    assert p["press"]["total"] == 0


def test_press_respeta_exclusion_reason(tmp_db):
    """Si algún día un backfill retroactivo marca una nota de prensa como
    irrelevante (exclusion_reason), no debe contarse en payload["press"]
    — mismo tratamiento que el resto del reporte."""
    _seed(tmp_db, [_prensa(1)])
    conn = tmp_db
    conn.execute("UPDATE mentions SET exclusion_reason = 'sin_contexto_aeronautico' WHERE id = 'm-1'")
    conn.commit()

    p = aggregate.build_payload(conn)
    assert p["press"]["total"] == 0


# ── data_quality declara el alcance ─────────────────────────────────────

def test_data_quality_declara_alcance_de_kpis(tmp_db):
    _seed(tmp_db, [_m(1), _prensa(2), _resena(3)])
    p = aggregate.build_payload(tmp_db)

    q = p["data_quality"]
    assert q["press_excluded_from_kpis"] is True
    assert "prensa" not in q["kpi_platforms"]
    assert "resena" in q["kpi_platforms"]
    assert q["press_total"] == 1
    assert q["reviews_total"] == 1
