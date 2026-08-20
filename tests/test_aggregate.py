from config import REPORT_WINDOW_START
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


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_kpis_basicos(tmp_db):
    _seed(tmp_db, [_m(1), _m(2, is_complaint=0, complaint_driver=None)])
    p = aggregate.build_payload(tmp_db)
    assert p["kpis"]["total"] == 2
    assert p["kpis"]["complaints"] == 1
    assert p["kpis"]["complaint_rate"] == 50.0


def test_timeline_excluye_fechas_desconocidas(tmp_db):
    _seed(tmp_db, [
        _m(1),
        _m(2, published_at=None, date_confidence="unknown"),
        # Caso que aísla la regla: published_at SÍ está presente, pero la
        # confianza es 'unknown'. Si el filtro solo mirara published_at
        # (ignorando date_confidence), esta mención se colaría al timeline.
        _m(3, date_confidence="unknown"),
    ])
    p = aggregate.build_payload(tmp_db)
    fechas = [punto["date"] for punto in p["timeline"]]
    assert fechas == ["2026-05-01"]
    assert p["timeline"][0]["counts"]["tiktok"] == 1


def test_sentiment_excluye_unclassified(tmp_db):
    _seed(tmp_db, [
        _m(1, sentiment_negative=1.0, sentiment_positive=0.0, sentiment_neutral=0.0),
        _m(2, classification_status="unclassified",
           sentiment_negative=None, sentiment_positive=None, sentiment_neutral=None),
        # Caso que aísla la regla: classification_status es 'unclassified' pero
        # los campos de sentiment SÍ tienen valores (p.ej. una reclasificación
        # a medias). Si el filtro mirara la presencia de sentiment en vez del
        # status, esta mención contaminaría el promedio.
        _m(3, classification_status="unclassified",
           sentiment_negative=0.0, sentiment_positive=1.0, sentiment_neutral=0.0),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["sentiment"]["counts"]["negative"] == 1
    assert p["sentiment"]["pct"]["negative"] == 100.0
    assert p["sentiment"]["classified_count"] == 1


def test_sentimiento_por_etiqueta_dominante_cuenta_bien(tmp_db):
    """
    El sentiment se muestra como conteo de menciones por etiqueta dominante
    (la de mayor probabilidad), no como promedio de probabilidades — "52,6%
    positivo" debe significar "52,6% de las menciones son positivas".
    Incluye un caso de empate exacto (positive == negative): el desempate
    definido es negative > neutral > positive, así que esa mención cuenta
    como negativa.
    """
    _seed(tmp_db, [
        _m(1, sentiment_positive=0.7, sentiment_negative=0.2, sentiment_neutral=0.1),
        _m(2, sentiment_positive=0.1, sentiment_negative=0.8, sentiment_neutral=0.1),
        _m(3, sentiment_positive=0.1, sentiment_negative=0.1, sentiment_neutral=0.8),
        # Empate exacto positive/negative: el desempate lo manda a negative.
        _m(4, sentiment_positive=0.5, sentiment_negative=0.5, sentiment_neutral=0.0),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["sentiment"]["counts"] == {"positive": 1, "negative": 2, "neutral": 1}
    assert p["sentiment"]["pct"]["negative"] == 50.0
    assert p["sentiment"]["classified_count"] == 4
    # El promedio de probabilidades se conserva bajo otra clave, no se usa
    # como el número que se muestra.
    assert "avg_probabilities" in p["sentiment"]


def test_drivers_ordenados_por_volumen(tmp_db):
    _seed(tmp_db, [
        _m(1, complaint_driver="equipaje"),
        _m(2, complaint_driver="equipaje"),
        _m(3, complaint_driver="demora"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["drivers"][0]["driver"] == "equipaje"
    assert p["drivers"][0]["count"] == 2
    assert p["drivers"][1]["driver"] == "demora"


def test_driver_pct_total_cuadra(tmp_db):
    """
    drivers[].pct es el % que representa cada driver sobre el total de
    quejas — el número que alimenta la columna "% Total" del heatmap
    driver×plataforma (Cambio 4). Debe cuadrar con el conteo real y sumar
    100% entre todos los drivers presentes.
    """
    _seed(tmp_db, [
        _m(1, complaint_driver="equipaje"),
        _m(2, complaint_driver="equipaje"),
        _m(3, complaint_driver="equipaje"),
        _m(4, complaint_driver="demora"),
    ])
    p = aggregate.build_payload(tmp_db)
    por_driver = {d["driver"]: d for d in p["drivers"]}
    assert por_driver["equipaje"]["pct"] == 75.0
    assert por_driver["demora"]["pct"] == 25.0
    assert round(sum(d["pct"] for d in p["drivers"]), 1) == 100.0


def test_colapsa_repeticiones_mismo_autor_y_texto(tmp_db):
    """
    Dos filas del mismo autor con el mismo texto pero distinta source_url
    (el caso real: alejandra.caicho pegando el mismo comentario en URLs de
    comentario distintas) se colapsan en una sola voz. repeat_count cuenta
    las repeticiones y engagement suma el alcance de todas.
    """
    _seed(tmp_db, [
        _m(1, author="alejandra.caicho", text="Avianca canceló mi vuelo otra vez",
           source_url="https://x.com/c/1", likes=10, shares=1, comments_count=0),
        _m(2, author="alejandra.caicho", text="Avianca canceló mi vuelo otra vez",
           source_url="https://x.com/c/2", likes=5, shares=0, comments_count=2),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["kpis"]["total"] == 1
    voz = p["mentions"][0]
    assert voz["repeat_count"] == 2
    assert voz["engagement"] == 18  # (10+1+0) + (5+0+2)


def test_no_colapsa_autores_distintos_mismo_texto(tmp_db):
    """Mismo texto, autores distintos: son dos voces reales, no se fusionan."""
    _seed(tmp_db, [
        _m(1, author="autor_a", text="Avianca canceló mi vuelo otra vez",
           source_url="https://x.com/c/1"),
        _m(2, author="autor_b", text="Avianca canceló mi vuelo otra vez",
           source_url="https://x.com/c/2"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["kpis"]["total"] == 2
    assert all(m["repeat_count"] == 1 for m in p["mentions"])


def test_collapsed_repeats_y_unique_voices_en_payload(tmp_db):
    _seed(tmp_db, [
        _m(1, author="alejandra.caicho", text="mismo texto repetido",
           source_url="https://x.com/c/1"),
        _m(2, author="alejandra.caicho", text="mismo texto repetido",
           source_url="https://x.com/c/2"),
        _m(3, author="alejandra.caicho", text="mismo texto repetido",
           source_url="https://x.com/c/3"),
        _m(4, author="otro_autor", text="comentario distinto",
           source_url="https://x.com/c/4"),
    ])
    p = aggregate.build_payload(tmp_db)
    # 4 filas crudas, 2 voces únicas -> 2 filas absorbidas por el colapso.
    assert p["data_quality"]["collapsed_repeats"] == 2
    assert p["data_quality"]["unique_voices"] == 2
    assert p["data_quality"]["total"] == 2


def test_driver_por_plataforma(tmp_db):
    _seed(tmp_db, [
        _m(1, platform="tiktok", complaint_driver="equipaje"),
        _m(2, platform="instagram", complaint_driver="equipaje"),
    ])
    p = aggregate.build_payload(tmp_db)
    celda = [c for c in p["driver_by_platform"]
             if c["driver"] == "equipaje" and c["platform"] == "instagram"]
    assert celda[0]["count"] == 1


def test_top_complaints_sin_alcance_van_al_grupo_without_reach_por_interacciones(tmp_db):
    """
    Ninguna de estas dos quejas tiene `views` (no se corrió el
    enriquecimiento de alcance) — deben caer en el grupo without_reach,
    ordenadas por interactions (likes+shares+comments_count+saves), no
    inventarse un puesto en with_reach.
    """
    _seed(tmp_db, [
        _m(1, likes=5, shares=0, comments_count=0),
        _m(2, likes=500, shares=100, comments_count=50),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["top_complaints"]["with_reach"] == []
    sin_alcance = p["top_complaints"]["without_reach"]
    assert sin_alcance[0]["id"] == "m-2"
    assert sin_alcance[0]["interactions"] == 650
    assert sin_alcance[0]["engagement"] == 650  # se conserva, no se rompe


def test_top_complaints_con_alcance_se_rankean_por_views_no_por_engagement(tmp_db):
    """
    Regresión del hallazgo central de la Tarea 3: engagement subestima el
    alcance real. Una queja con pocas views pero mucho engagement sumado NO
    debe ganarle a una con más alcance real — el ranking usa views.
    """
    _seed(tmp_db, [
        _m(1, likes=2000, shares=200, comments_count=16, views=2000),   # engagement alto, alcance chico
        _m(2, likes=1961, shares=200, comments_count=55, views=61500),  # engagement menor, alcance real mayor
    ])
    p = aggregate.build_payload(tmp_db)
    con_alcance = p["top_complaints"]["with_reach"]
    assert [f["id"] for f in con_alcance] == ["m-2", "m-1"]
    assert con_alcance[0]["views"] == 61500


def test_top_complaints_mezcla_con_y_sin_alcance_no_se_mezclan_en_un_solo_orden(tmp_db):
    _seed(tmp_db, [
        _m(1, views=100, likes=10, shares=0, comments_count=0),
        _m(2, views=None, likes=99999, shares=0, comments_count=0),
    ])
    p = aggregate.build_payload(tmp_db)
    assert [f["id"] for f in p["top_complaints"]["with_reach"]] == ["m-1"]
    assert [f["id"] for f in p["top_complaints"]["without_reach"]] == ["m-2"]


def test_data_quality_reporta_huecos(tmp_db):
    _seed(tmp_db, [
        _m(1),
        _m(2, published_at=None, date_confidence="unknown"),
        _m(3, classification_status="unclassified"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["unknown_date"] == 1
    assert p["data_quality"]["unclassified"] == 1
    assert p["data_quality"]["total"] == 3


def test_filtered_last_run_no_duplica_entre_corridas(tmp_db):
    """
    seed() recalcula filtered_count sobre el archivo completo cada vez que
    corre, sin importar cuánto de eso ya estaba en la DB. Dos corridas del
    mismo archivo (p.ej. re-ejecutar el seed por error) no deben SUMAR sus
    filtered_count — eso reportaría descartes que no existen. Solo importa
    la corrida más reciente que terminó.
    """
    for _ in range(2):
        run_id = db.start_run(tmp_db, "seed", None)
        db.upsert_mentions(tmp_db, [_m(1)], run_id)
        db.finish_run(tmp_db, run_id, raw_count=100, filtered_count=96,
                       inserted_count=1, duplicate_count=0)

    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["filtered_last_run"] == 96
    assert p["data_quality"]["last_run_mode"] == "seed"
    assert p["data_quality"]["last_run_at"] is not None


def test_short_text_last_run_llega_de_punta_a_punta_al_payload(tmp_db):
    """
    normalize() descarta comentarios de solo emoji antes de que corra
    relevance, así que no aparecen en filtered_count (Important #2). El
    contador debe viajar de finish_run() hasta el payload del dashboard,
    con el mismo criterio de 'última corrida' que filtered_last_run.
    """
    run_id = db.start_run(tmp_db, "backfill", "2026-04-19")
    db.upsert_mentions(tmp_db, [_m(1)], run_id)
    db.finish_run(tmp_db, run_id, raw_count=1310, filtered_count=71,
                  inserted_count=1, duplicate_count=0, short_text_count=201)

    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["short_text_last_run"] == 201


def test_short_text_last_run_es_cero_sin_corridas(tmp_db):
    _seed(tmp_db, [_m(1)])
    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["short_text_last_run"] == 0


def test_mentions_incluye_todo_para_la_tabla(tmp_db):
    _seed(tmp_db, [_m(1), _m(2)])
    p = aggregate.build_payload(tmp_db)
    assert len(p["mentions"]) == 2
    assert set(p["mentions"][0]) >= {
        "id", "platform", "text", "author", "published_at",
        "source_url", "complaint_driver", "is_complaint", "engagement",
        "repeat_count",
        # Tarea 3: las tres capas — nunca sumadas en un compuesto.
        "likes", "shares", "comments_count", "saves", "views",
        "reach_source", "interactions", "interaction_rate",
    }


# ── Tarea 3: las tres capas de engagement (alcance / interacciones / tasa) ─

def test_metricas_que_no_aplican_a_la_plataforma_quedan_none_no_cero(tmp_db):
    """
    web no tiene NINGUNA métrica de engagement — DataForSEO nunca la
    entrega. Deben quedar None (guion en el dashboard), no 0, aunque el
    schema por defecto guarde 0 en likes/shares/comments_count.
    """
    _seed(tmp_db, [_m(1, platform="web", likes=0, shares=0, comments_count=0)])
    p = aggregate.build_payload(tmp_db)
    voz = p["mentions"][0]
    assert voz["likes"] is None
    assert voz["shares"] is None
    assert voz["comments_count"] is None
    assert voz["saves"] is None
    assert voz["views"] is None
    assert voz["interactions"] is None
    assert voz["interaction_rate"] is None


def test_instagram_solo_likes_y_views_aplican(tmp_db):
    """Instagram: likes (propio del comentario) y views (prestado del post)
    aplican; shares/comments_count/saves no — un comentario no los tiene."""
    _seed(tmp_db, [_m(1, platform="instagram", likes=7, shares=0, comments_count=0,
                       views=32600, reach_source="post")])
    p = aggregate.build_payload(tmp_db)
    voz = p["mentions"][0]
    assert voz["likes"] == 7
    assert voz["shares"] is None
    assert voz["comments_count"] is None
    assert voz["saves"] is None
    assert voz["views"] == 32600
    assert voz["reach_source"] == "post"


def test_tiktok_las_cinco_metricas_aplican(tmp_db):
    _seed(tmp_db, [_m(1, platform="tiktok", likes=1961, shares=200, comments_count=55,
                       saves=249, views=61500, reach_source="propio")])
    p = aggregate.build_payload(tmp_db)
    voz = p["mentions"][0]
    assert voz["likes"] == 1961
    assert voz["shares"] == 200
    assert voz["comments_count"] == 55
    assert voz["saves"] == 249
    assert voz["views"] == 61500
    assert voz["reach_source"] == "propio"


def test_interactions_suma_las_cuatro_capas_de_interaccion(tmp_db):
    _seed(tmp_db, [_m(1, platform="tiktok", likes=1961, shares=200, comments_count=55,
                       saves=249, views=61500)])
    p = aggregate.build_payload(tmp_db)
    voz = p["mentions"][0]
    assert voz["interactions"] == 1961 + 200 + 55 + 249


def test_interaction_rate_nunca_divide_por_cero(tmp_db):
    """views=0 (o ausente) no debe reventar con ZeroDivisionError — la
    tasa queda None, no infinito ni una excepción."""
    _seed(tmp_db, [
        _m(1, platform="tiktok", likes=10, shares=0, comments_count=0, saves=0, views=0),
        _m(2, platform="tiktok", author="autor_sin_views", likes=10, shares=0,
           comments_count=0, saves=0, views=None),
    ])
    p = aggregate.build_payload(tmp_db)
    assert all(v["interaction_rate"] is None for v in p["mentions"])


def test_interaction_rate_calcula_bien_cuando_hay_alcance(tmp_db):
    _seed(tmp_db, [_m(1, platform="tiktok", likes=200, shares=100, comments_count=100,
                       saves=0, views=2000)])
    p = aggregate.build_payload(tmp_db)
    voz = p["mentions"][0]
    # interactions = 400, views = 2000 -> 20.0%
    assert voz["interaction_rate"] == 20.0


def test_saves_ausente_en_una_repeticion_no_convierte_el_total_en_cero(tmp_db):
    """
    Dos repeticiones de la misma voz: una con saves medido, otra sin
    (fila legacy sin raw completo). El total debe sumar lo que SÍ se
    conoce, no tratar la ausencia como 0 y no perder el dato conocido.
    """
    _seed(tmp_db, [
        _m(1, platform="tiktok", author="spammer", text="mismo texto repetido",
           source_url="https://x.com/c/1", saves=249, views=61500),
        _m(2, platform="tiktok", author="spammer", text="mismo texto repetido",
           source_url="https://x.com/c/2", saves=None, views=None),
    ])
    p = aggregate.build_payload(tmp_db)
    assert len(p["mentions"]) == 1
    voz = p["mentions"][0]
    assert voz["saves"] == 249
    assert voz["views"] == 61500


def test_reach_source_no_se_pierde_si_la_repeticion_mas_antigua_no_lo_trae(tmp_db):
    """
    Regresión verificada visualmente en el dashboard real: una voz
    repetida donde la ocurrencia MÁS ANTIGUA no tiene views (comentario de
    un post sin backfill de alcance) pero una repetición más reciente sí
    las tiene (post con backfill) — reach_source debe reflejar de dónde
    viene el número sumado, no perderse por mirar solo la más antigua.
    """
    _seed(tmp_db, [
        _m(1, platform="instagram", author="spammer3", text="mismo texto repetido otra vez",
           source_url="https://x.com/e/1", likes=0, shares=0, comments_count=0,
           published_at="2026-05-01T10:00:00+00:00",  # más antigua: SIN views/reach_source
           views=None, reach_source=None),
        _m(2, platform="instagram", author="spammer3", text="mismo texto repetido otra vez",
           source_url="https://x.com/e/2", likes=0, shares=0, comments_count=0,
           published_at="2026-06-01T10:00:00+00:00",  # más reciente: CON views/reach_source
           views=32600, reach_source="post"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert len(p["mentions"]) == 1
    voz = p["mentions"][0]
    assert voz["views"] == 32600
    assert voz["reach_source"] == "post"


def test_saves_todas_las_repeticiones_sin_dato_queda_none(tmp_db):
    """Si NINGUNA repetición trae saves/views, el total es None, no 0 —
    la ausencia no se convierte en un cero al sumar."""
    _seed(tmp_db, [
        _m(1, platform="tiktok", author="spammer2", text="otro texto repetido",
           source_url="https://x.com/d/1", saves=None, views=None),
        _m(2, platform="tiktok", author="spammer2", text="otro texto repetido",
           source_url="https://x.com/d/2", saves=None, views=None),
    ])
    p = aggregate.build_payload(tmp_db)
    voz = p["mentions"][0]
    assert voz["saves"] is None
    assert voz["views"] is None


# ── Tarea 4: cobertura por métrica y plataforma (bloque 8) ────────────────

def test_metric_coverage_cuenta_filas_reales_por_plataforma(tmp_db):
    _seed(tmp_db, [
        _m(1, platform="tiktok", author="a", saves=249, views=61500),
        _m(2, platform="tiktok", author="b", saves=None, views=None),  # legacy sin raw
        _m(3, platform="instagram", author="c", likes=7, views=32600),
        _m(4, platform="web", author="d"),
    ])
    p = aggregate.build_payload(tmp_db)
    cov = p["data_quality"]["metric_coverage"]

    assert cov["tiktok"]["total"] == 2
    assert cov["tiktok"]["saves"] == 1   # solo una de las dos voces tiktok tiene saves
    assert cov["tiktok"]["views"] == 1

    assert cov["instagram"]["total"] == 1
    assert cov["instagram"]["likes"] == 1
    assert cov["instagram"]["shares"] == 0   # nunca aplica a instagram
    assert cov["instagram"]["views"] == 1

    assert cov["web"]["total"] == 1
    assert cov["web"]["likes"] == 0
    assert cov["web"]["views"] == 0


def test_metric_applies_declara_que_metricas_existen_por_plataforma(tmp_db):
    """
    metric_applies distingue "nunca aplica" de "aplica pero hoy no hay
    dato" — el dashboard lo usa para no confundir "0 de N" con "no aplica".
    """
    _seed(tmp_db, [_m(1)])
    p = aggregate.build_payload(tmp_db)
    applies = p["data_quality"]["metric_applies"]

    assert applies["web"]["likes"] is False
    assert applies["web"]["views"] is False
    assert applies["tiktok"]["saves"] is True
    assert applies["tiktok"]["views"] is True
    assert applies["instagram"]["likes"] is True
    assert applies["instagram"]["shares"] is False
    assert applies["instagram"]["comments_count"] is False
    assert applies["instagram"]["saves"] is False
    assert applies["instagram"]["views"] is True


# ── Ventana de reporte (REPORT_WINDOW_START) ──────────────────────────
#
# El backfill se pidió con --since 2026-04-19, pero el actor de TikTok
# ignoró oldestPostDate y devolvió videos de 2023-2025. Esas menciones son
# reales y siguen en la DB, pero quedan fuera del análisis: la ventana se
# aplica de forma consistente a todo (KPIs, timeline, drivers, sentiment,
# emociones, tabla, top quejas), sin excepciones por bloque.

def test_mencion_anterior_a_la_ventana_no_aparece_en_ningun_bloque(tmp_db):
    _seed(tmp_db, [
        _m(1, author="autor_2023", published_at="2023-03-23T00:00:00+00:00",
           is_complaint=1, complaint_driver="equipaje"),
        _m(2, author="autor_2026", published_at="2026-05-01T00:00:00+00:00",
           is_complaint=1, complaint_driver="demora"),
    ])
    p = aggregate.build_payload(tmp_db)

    # KPIs: solo la de 2026 cuenta.
    assert p["kpis"]["total"] == 1
    assert p["kpis"]["complaints"] == 1
    assert p["kpis"]["date_from"] == "2026-05-01"

    # Tabla y top quejas.
    assert len(p["mentions"]) == 1
    assert p["mentions"][0]["author"] == "autor_2026"
    todas_las_quejas = p["top_complaints"]["with_reach"] + p["top_complaints"]["without_reach"]
    assert all(f["author"] == "autor_2026" for f in todas_las_quejas)

    # Drivers, timeline, sentiment y calidad de datos.
    assert [d["driver"] for d in p["drivers"]] == ["demora"]
    assert all(punto["date"] != "2023-03-23" for punto in p["timeline"])
    assert p["data_quality"]["total"] == 1
    assert p["data_quality"]["by_platform"] == {"tiktok": 1}


def test_outside_window_cuenta_las_que_quedan_fuera(tmp_db):
    _seed(tmp_db, [
        _m(1, author="a", published_at="2023-03-23T00:00:00+00:00"),
        _m(2, author="b", published_at="2024-06-01T00:00:00+00:00"),
        _m(3, author="c", published_at="2026-05-01T00:00:00+00:00"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["outside_window"] == 2
    assert p["data_quality"]["window_start"] == REPORT_WINDOW_START


def test_mencion_sin_fecha_sigue_contando_en_totales(tmp_db):
    """Sin published_at no hay fecha con la cual juzgar la ventana — se
    conserva en los totales, como ya hacía antes de esta corrección."""
    _seed(tmp_db, [
        _m(1, author="con_fecha", published_at="2026-05-01T00:00:00+00:00"),
        _m(2, author="sin_fecha", published_at=None, date_confidence="unknown"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["kpis"]["total"] == 2
    assert p["data_quality"]["total"] == 2
    assert p["data_quality"]["outside_window"] == 0
    assert p["data_quality"]["unknown_date"] == 1
