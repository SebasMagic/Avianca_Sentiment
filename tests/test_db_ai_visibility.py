"""
Visibilidad de marca en respuestas de IA — capa de persistencia (store/db.py).

Seis tablas nuevas, todas CREATE TABLE IF NOT EXISTS (aditivo, idempotente,
sin ALTER TABLE porque no son columnas nuevas sobre una tabla existente):
ai_brand_metrics, ai_brand_sources, ai_prompt_responses,
ai_prompt_brand_mentions, ai_search_mention_examples, search_share_of_voice.
Ver el docstring de SCHEMA en store/db.py para el porqué de cada una.
"""
import sqlite3

from store import db


def test_init_db_crea_las_seis_tablas_nuevas(tmp_db):
    tablas = {
        row[0] for row in tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for t in (
        "ai_brand_metrics", "ai_brand_sources", "ai_prompt_responses",
        "ai_prompt_brand_mentions", "ai_search_mention_examples",
        "search_share_of_voice",
    ):
        assert t in tablas


def test_migracion_no_pierde_filas_existentes_de_mentions_al_agregar_tablas_ai():
    """
    Una DB "vieja" (solo mentions/runs, sin las tablas de visibilidad IA)
    debe ganar las seis tablas nuevas al pasar por init_db, sin perder
    ninguna fila de las que ya tenía. Esto es lo que protege
    data/avianca.db en la migración real.
    """
    conn = sqlite3.connect(":memory:")
    # Schema completo de `mentions` previo a la columna `rating` (ver
    # test_migracion_agrega_rating_sin_perder_filas en test_db.py) — hace
    # falta el schema COMPLETO, no uno recortado: SCHEMA crea índices
    # sobre columnas como is_complaint, y CREATE TABLE IF NOT EXISTS no
    # reemplaza una tabla que ya existe, así que una tabla parcial haría
    # fallar esos CREATE INDEX antes de llegar a las tablas de este cambio.
    conn.executescript("""
        CREATE TABLE mentions (
            id                    TEXT PRIMARY KEY,
            fingerprint           TEXT NOT NULL UNIQUE,
            brand                 TEXT NOT NULL DEFAULT 'Avianca',
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
            run_id                TEXT,
            exclusion_reason      TEXT
        );
        CREATE TABLE runs (
            id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
            mode TEXT NOT NULL, since TEXT
        );
    """)
    conn.execute(
        "INSERT INTO mentions (id, fingerprint, platform, text, "
        "date_confidence, classification_status) "
        "VALUES ('m1', 'fp1', 'tiktok', 'hola', 'exact', 'unclassified')"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)

    fila = conn.execute("SELECT * FROM mentions WHERE id = 'm1'").fetchone()
    assert fila["id"] == "m1"

    tablas = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "ai_brand_metrics" in tablas
    assert "search_share_of_voice" in tablas
    conn.close()


def test_init_db_es_idempotente_para_las_tablas_nuevas(tmp_db):
    """Correr init_db dos veces no falla ni duplica nada."""
    db.init_db(tmp_db)
    tablas = [
        row[0] for row in tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert tablas.count("ai_brand_metrics") == 1


# ── ai_brand_metrics / ai_brand_sources ──────────────────────────────────

def test_insert_ai_brand_metrics_y_lectura_por_marca(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    n = db.insert_ai_brand_metrics(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
        "domain": "avianca.com", "platform": "google",
        "mentions": 1091, "ai_search_volume": 839350,
        "source_endpoint": "target_metrics", "raw": {"foo": "bar"},
    }], run_id)
    assert n == 1

    filas = db.ai_brand_metrics_for_brand(tmp_db, "Avianca")
    assert len(filas) == 1
    assert filas[0]["mentions"] == 1091
    assert filas[0]["domain"] == "avianca.com"
    assert filas[0]["raw"] == {"foo": "bar"}  # _to_dict ya lo deserializa

    assert db.ai_brand_metrics_for_brand(tmp_db, "LATAM") == []


def test_insert_ai_brand_sources_marca_dominio_propio_y_competidor(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    db.insert_ai_brand_sources(tmp_db, [
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "cited_domain": "www.avianca.com", "mentions": 1091,
         "ai_search_volume": 839350, "is_own_domain": True,
         "is_competitor_domain": False, "source_endpoint": "target_metrics"},
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "cited_domain": "www.latamairlines.com", "mentions": 246,
         "ai_search_volume": 161710, "is_own_domain": False,
         "is_competitor_domain": True, "source_endpoint": "target_metrics"},
    ], run_id)

    filas = db.ai_brand_sources_for_brand(tmp_db, "Avianca")
    assert len(filas) == 2
    competidor = next(f for f in filas if f["cited_domain"] == "www.latamairlines.com")
    assert competidor["is_competitor_domain"] == 1
    assert competidor["is_own_domain"] == 0


# ── ai_prompt_responses / ai_prompt_brand_mentions ───────────────────────

def test_insert_ai_prompt_response_con_menciones_por_marca(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    response_id = db.insert_ai_prompt_response(
        tmp_db,
        {
            "captured_at": "2026-08-22T00:00:00+00:00", "platform": "chat_gpt",
            "model": "gpt-4o-mini-2024-07-18",
            "prompt": "¿Cuál es la mejor aerolínea para volar dentro de Colombia?",
            "prompt_scope": "category", "subject_brand": None,
            "response_text": "Avianca y LATAM son las principales opciones...",
            "input_tokens": 20, "output_tokens": 150, "money_spent": 0.0007,
            "raw": {"foo": "bar"},
        },
        [
            {"brand": "Avianca", "appears": True, "position": 1,
             "sentiment_positive": 0.6, "sentiment_negative": 0.1,
             "sentiment_neutral": 0.3, "emotion": "neutral",
             "classification_status": "classified"},
            {"brand": "LATAM", "appears": True, "position": 2,
             "sentiment_positive": 0.5, "sentiment_negative": 0.1,
             "sentiment_neutral": 0.4, "emotion": "neutral",
             "classification_status": "classified"},
        ],
        run_id,
    )
    assert response_id

    avianca_rows = db.ai_prompt_responses_for_brand(tmp_db, "Avianca")
    assert len(avianca_rows) == 1
    assert avianca_rows[0]["appears"] == 1
    assert avianca_rows[0]["position"] == 1
    assert "Avianca y LATAM" in avianca_rows[0]["response_text"]

    latam_rows = db.ai_prompt_responses_for_brand(tmp_db, "LATAM")
    assert len(latam_rows) == 1
    assert latam_rows[0]["position"] == 2
    # Mismo texto de respuesta, no duplicado en la tabla de respuestas —
    # solo la extracción por marca se repite.
    assert latam_rows[0]["response_text"] == avianca_rows[0]["response_text"]


def test_ai_prompt_brand_mention_no_aparece_queda_sin_posicion(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    db.insert_ai_prompt_response(
        tmp_db,
        {
            "captured_at": "2026-08-22T00:00:00+00:00", "platform": "chat_gpt",
            "model": "gpt-4o-mini", "prompt": "¿Es confiable Avianca?",
            "prompt_scope": "brand", "subject_brand": "Avianca",
            "response_text": "Avianca es una aerolínea confiable.",
        },
        [
            {"brand": "Avianca", "appears": True, "position": 1},
            {"brand": "LATAM", "appears": False, "position": None},
        ],
        run_id,
    )
    latam_rows = db.ai_prompt_responses_for_brand(tmp_db, "LATAM")
    assert latam_rows[0]["appears"] == 0
    assert latam_rows[0]["position"] is None


# ── ai_search_mention_examples ───────────────────────────────────────────

def test_insert_ai_search_mention_examples(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    n = db.insert_ai_search_mention_examples(tmp_db, [{
        "brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
        "platform": "google_ai_overview", "question": "avianca check-in",
        "answer": "El check-in de Avianca se realiza...",
        "ai_search_volume": 110000, "top_source_domain": "www.avianca.com",
        "top_source_url": "https://www.avianca.com/es/mi-reserva",
        "raw": {},
    }], run_id)
    assert n == 1
    filas = db.ai_search_mention_examples_for_brand(tmp_db, "Avianca")
    assert filas[0]["question"] == "avianca check-in"
    assert filas[0]["ai_search_volume"] == 110000


# ── search_share_of_voice ────────────────────────────────────────────────

def test_insert_search_share_of_voice_por_intencion(tmp_db):
    run_id = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    n = db.insert_search_share_of_voice(tmp_db, [
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "keyword": "avianca reclamo", "intent": "problema",
         "engine": "google_ads", "search_volume": 390},
        {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
         "keyword": "avianca vuelos", "intent": "comercial",
         "engine": "google_ads", "search_volume": 12000},
    ], run_id)
    assert n == 2
    filas = db.search_share_of_voice_for_brand(tmp_db, "Avianca")
    problema = next(f for f in filas if f["intent"] == "problema")
    comercial = next(f for f in filas if f["intent"] == "comercial")
    assert problema["search_volume"] == 390
    assert comercial["search_volume"] == 12000
