"""
dashboard/ai_visibility_aggregate.py — agregaciones del bloque de
visibilidad en IA y de share of voice. Regla dura: sin datos capturados,
el payload lo declara (own=None, has_data=False) — nunca rellena con 0.
"""
from dashboard import ai_visibility_aggregate as agg
from dashboard.ai_visibility_aggregate import _excerpt
from store import db


# ── _excerpt: limpia markdown crudo (chat_gpt/Google AI Overview lo
# devuelven real) antes de mostrarlo como texto plano en una tarjeta ────

def test_excerpt_quita_negrita_markdown():
    assert _excerpt("Avianca tiene **buen servicio**.") == "Avianca tiene buen servicio."


def test_excerpt_quita_enlaces_markdown_dejando_solo_el_texto():
    texto = "Revisa el [check-in online](https://www.avianca.com/checkin) antes de viajar."
    assert _excerpt(texto) == "Revisa el check-in online antes de viajar."


def test_excerpt_quita_imagenes_markdown_dejando_el_alt():
    """Grabado real (LATAM, 2026-08-22): search_mentions devolvió una
    respuesta con "![Todo lo que necesitas...](url)" — sin la rama de
    imagen, un link normal deja el "!" colgando sin su corchete."""
    texto = "![Vacaciones en Aruba](https://x.com/img.png) es un buen destino."
    assert _excerpt(texto) == "Vacaciones en Aruba es un buen destino."
    assert "!" not in _excerpt(texto)


def test_excerpt_quita_backticks_de_codigo_inline():
    assert _excerpt("Aruba es una `isla caribeña soleada`.") == "Aruba es una isla caribeña soleada."


def test_excerpt_quita_encabezados_al_inicio_de_linea():
    texto = "### Avianca\n- Ruta: fuerte en Colombia."
    assert _excerpt(texto) == "Avianca\n- Ruta: fuerte en Colombia."


def test_excerpt_no_toca_el_contenido_real_solo_la_sintaxis():
    """La limpieza es de FORMATO, no de contenido — ninguna palabra real
    del texto debe perderse, solo los símbolos de marcado."""
    texto = "Avianca ha mantenido un **buen historial de seguridad** según [Skytrax](https://skytrax.com)."
    resultado = _excerpt(texto)
    assert "buen historial de seguridad" in resultado
    assert "Skytrax" in resultado
    assert "**" not in resultado
    assert "[" not in resultado and "](" not in resultado


def test_excerpt_trunca_respetando_el_limite_tras_limpiar_markdown():
    texto = "**" + ("palabra " * 200) + "**"
    resultado = _excerpt(texto)
    assert len(resultado) <= agg.EXCERPT_LEN + 1  # +1 por el "…" final
    assert resultado.endswith("…")


def _seed_metrics_and_sources(conn, brand, captured_at, mentions=1000,
                               source_endpoint="target_metrics", run_id=None):
    run_id = run_id or db.start_run(conn, "ai_visibility", None, brand=brand)
    db.insert_ai_brand_metrics(conn, [{
        "brand": brand, "captured_at": captured_at, "domain": f"{brand.lower()}.com",
        "platform": "google", "mentions": mentions, "ai_search_volume": mentions * 700,
        "source_endpoint": source_endpoint, "raw": {},
    }], run_id)
    return run_id


# ── build_ai_visibility_payload: sin datos ───────────────────────────────

def test_sin_ninguna_captura_declara_own_none_no_ceros(tmp_db):
    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    assert p["own"] is None
    assert p["has_metrics"] is False
    assert p["competitors"] == []
    assert p["missing_competitors"] == ["LATAM"]
    assert p["has_prompts"] is False
    assert p["has_search_examples"] is False


# ── own vs. competitors ───────────────────────────────────────────────────

def test_own_y_competidor_con_datos_quedan_comparables(tmp_db):
    _seed_metrics_and_sources(tmp_db, "Avianca", "2026-08-22T00:00:00+00:00", mentions=1091)
    _seed_metrics_and_sources(tmp_db, "LATAM", "2026-08-22T00:00:00+00:00", mentions=1079)

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    assert p["own"]["mentions"] == 1091
    assert len(p["competitors"]) == 1
    assert p["competitors"][0]["brand"] == "LATAM"
    assert p["competitors"][0]["mentions"] == 1079
    assert p["missing_competitors"] == []


def test_competidor_sin_captura_queda_en_missing_no_en_cero(tmp_db):
    _seed_metrics_and_sources(tmp_db, "Avianca", "2026-08-22T00:00:00+00:00")

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    assert p["competitors"] == []
    assert p["missing_competitors"] == ["LATAM"]


# ── fuentes citadas: mismo captured_at que la captura elegida ────────────

def test_fuentes_solo_de_la_captura_mas_reciente_no_de_una_vieja(tmp_db):
    """Dos capturas en fechas distintas: las fuentes de la VIEJA no deben
    colarse junto a las métricas de la más reciente."""
    run1 = _seed_metrics_and_sources(tmp_db, "Avianca", "2026-08-01T00:00:00+00:00", mentions=900)
    db.insert_ai_brand_sources(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-01T00:00:00+00:00",
        "cited_domain": "www.fuente-vieja.com", "mentions": 5, "ai_search_volume": 100,
        "is_own_domain": False, "is_competitor_domain": False, "source_endpoint": "target_metrics",
    }], run1)

    run2 = _seed_metrics_and_sources(tmp_db, "Avianca", "2026-08-22T00:00:00+00:00", mentions=1091)
    db.insert_ai_brand_sources(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
        "cited_domain": "www.latamairlines.com", "mentions": 246, "ai_search_volume": 161710,
        "is_own_domain": False, "is_competitor_domain": True, "source_endpoint": "target_metrics",
    }], run2)

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    dominios = {s["domain"] for s in p["own"]["sources"]}
    assert dominios == {"www.latamairlines.com"}
    assert "www.fuente-vieja.com" not in dominios


def test_fuente_de_competidor_marcada_is_competitor_domain(tmp_db):
    run_id = _seed_metrics_and_sources(tmp_db, "Avianca", "2026-08-22T00:00:00+00:00")
    db.insert_ai_brand_sources(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
        "cited_domain": "www.latamairlines.com", "mentions": 246, "ai_search_volume": 161710,
        "is_own_domain": False, "is_competitor_domain": True, "source_endpoint": "target_metrics",
    }], run_id)

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    fuente = p["own"]["sources"][0]
    assert fuente["is_competitor_domain"] is True


# ── prompts: categoría vs. marca, agrupados por run_id ────────────────────

def test_prompts_se_separan_por_scope(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    db.insert_ai_prompt_response(tmp_db, {
        "captured_at": "2026-08-22T00:01:00+00:00", "platform": "chat_gpt", "model": "gpt-4o-mini",
        "prompt": "¿Cuál es la mejor aerolínea para volar dentro de Colombia?",
        "prompt_scope": "category", "subject_brand": None,
        "response_text": "Avianca es una opción sólida.",
    }, [{"brand": "Avianca", "appears": True, "position": 1,
         "sentiment_positive": 0.7, "sentiment_negative": 0.1, "sentiment_neutral": 0.2,
         "emotion": "happiness", "classification_status": "classified"}], run_id)
    db.insert_ai_prompt_response(tmp_db, {
        "captured_at": "2026-08-22T00:02:00+00:00", "platform": "chat_gpt", "model": "gpt-4o-mini",
        "prompt": "¿Es confiable Avianca?", "prompt_scope": "brand", "subject_brand": "Avianca",
        "response_text": "Sí, es confiable.",
    }, [{"brand": "Avianca", "appears": True, "position": 1}], run_id)
    db.finish_run(tmp_db, run_id, 2, 2, 2, 0)

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    assert len(p["category_prompts"]) == 1
    assert len(p["brand_prompts"]) == 1
    assert p["category_prompts"][0]["sentiment"] == "positive"
    assert p["brand_prompts"][0]["sentiment"] is None  # sin clasificar (appears sin sentiment)


def test_solo_se_muestra_la_corrida_mas_reciente_no_todo_el_historico(tmp_db):
    """Dos corridas completas de ai_visibility: la lista de prompts debe
    quedarse con la más reciente, no acumular ambas."""
    run1 = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    tmp_db.execute("UPDATE runs SET started_at = ? WHERE id = ?",
                    ("2026-08-01T00:00:00+00:00", run1))
    db.insert_ai_prompt_response(tmp_db, {
        "captured_at": "2026-08-01T00:01:00+00:00", "platform": "chat_gpt", "model": "gpt-4o-mini",
        "prompt": "prompt viejo", "prompt_scope": "brand", "subject_brand": "Avianca",
        "response_text": "respuesta vieja",
    }, [{"brand": "Avianca", "appears": True, "position": 1}], run1)
    db.finish_run(tmp_db, run1, 1, 1, 1, 0)

    run2 = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    tmp_db.execute("UPDATE runs SET started_at = ? WHERE id = ?",
                    ("2026-08-22T00:00:00+00:00", run2))
    db.insert_ai_prompt_response(tmp_db, {
        "captured_at": "2026-08-22T00:01:00+00:00", "platform": "chat_gpt", "model": "gpt-4o-mini",
        "prompt": "prompt nuevo", "prompt_scope": "brand", "subject_brand": "Avianca",
        "response_text": "respuesta nueva",
    }, [{"brand": "Avianca", "appears": True, "position": 1}], run2)
    db.finish_run(tmp_db, run2, 1, 1, 1, 0)

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    assert len(p["brand_prompts"]) == 1
    assert p["brand_prompts"][0]["prompt"] == "prompt nuevo"


# ── search_examples ────────────────────────────────────────────────────

def test_search_examples_recorta_a_max_quotes(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    filas = [{
        "brand": "Avianca", "captured_at": f"2026-08-22T00:0{i}:00+00:00",
        "platform": "google_ai_overview", "question": f"pregunta {i}",
        "answer": f"respuesta {i}", "ai_search_volume": 100 * i,
        "top_source_domain": "www.avianca.com", "top_source_url": "https://x",
    } for i in range(9)]
    db.insert_ai_search_mention_examples(tmp_db, filas, run_id)
    db.finish_run(tmp_db, run_id, 9, 9, 9, 0)

    p = agg.build_ai_visibility_payload(tmp_db, "Avianca")

    assert len(p["search_examples"]) == agg.MAX_QUOTES
    assert p["has_search_examples"] is True


# ── share of voice ────────────────────────────────────────────────────

def test_share_of_voice_sin_datos(tmp_db):
    sov = agg.build_share_of_voice_payload(tmp_db, "Avianca")
    assert sov["has_data"] is False
    assert sov["by_engine"] == {}


def test_share_of_voice_suma_por_intencion_y_motor(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    db.insert_search_share_of_voice(tmp_db, [
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "keyword": "avianca demanda", "intent": "problema", "engine": "google_ads",
         "search_volume": 10},
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "keyword": "avianca reclamo", "intent": "problema", "engine": "google_ads",
         "search_volume": 390},
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "keyword": "avianca vuelos", "intent": "comercial", "engine": "google_ads",
         "search_volume": 12000},
    ], run_id)
    db.finish_run(tmp_db, run_id, 3, 3, 3, 0)

    sov = agg.build_share_of_voice_payload(tmp_db, "Avianca")

    ga = sov["by_engine"]["google_ads"]
    assert ga["problema"] == 400
    assert ga["comercial"] == 12000
    assert ga["problem_pct"] == round(400 / 12400 * 100, 1)
    assert sov["has_data"] is True


def test_share_of_voice_ignora_corrida_vieja(tmp_db):
    run1 = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    tmp_db.execute("UPDATE runs SET started_at = ? WHERE id = ?",
                    ("2026-08-01T00:00:00+00:00", run1))
    db.insert_search_share_of_voice(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-01T00:00:00+00:00",
        "keyword": "avianca reclamo", "intent": "problema", "engine": "google_ads",
        "search_volume": 999,
    }], run1)
    db.finish_run(tmp_db, run1, 1, 1, 1, 0)

    run2 = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    tmp_db.execute("UPDATE runs SET started_at = ? WHERE id = ?",
                    ("2026-08-22T00:00:00+00:00", run2))
    db.insert_search_share_of_voice(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
        "keyword": "avianca reclamo", "intent": "problema", "engine": "google_ads",
        "search_volume": 390,
    }], run2)
    db.finish_run(tmp_db, run2, 1, 1, 1, 0)

    sov = agg.build_share_of_voice_payload(tmp_db, "Avianca")

    assert sov["by_engine"]["google_ads"]["problema"] == 390
