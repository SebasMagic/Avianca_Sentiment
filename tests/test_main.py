"""
Tests del cálculo de `since` para la corrida `weekly` (main.py).

Ningún test golpea una API: run_pipeline se ejerce con SCRAPERS
monkeypateado a vacío y sin menciones pendientes de clasificar, así que
classify_pending.run() retorna de inmediato sin llamar a DeepSeek.
"""
import sqlite3
from datetime import datetime, timezone

import main
from scrapers import apify_instagram
from store import db as store_db


def test_sin_corridas_previas_usa_7_dias_atras(tmp_db):
    now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    since = main.compute_weekly_since(tmp_db, now=now)
    assert since == "2026-08-13"


def test_con_corrida_previa_usa_su_fecha_de_inicio_menos_un_dia(tmp_db):
    run_id = store_db.start_run(tmp_db, "weekly", None)
    tmp_db.execute(
        "UPDATE runs SET started_at = ?, finished_at = ? WHERE id = ?",
        ("2026-08-10T08:00:00+00:00", "2026-08-10T08:05:00+00:00", run_id),
    )
    tmp_db.commit()

    since = main.compute_weekly_since(tmp_db)
    assert since == "2026-08-09"


def test_corrida_previa_sin_terminar_se_ignora(tmp_db):
    """Una corrida en curso o abortada (sin finished_at) no cuenta como
    'última corrida terminada' — si se usara, un backfill largo que
    sigue corriendo congelaría el since de las corridas weekly."""
    store_db.start_run(tmp_db, "weekly", None)  # nunca se llama finish_run

    now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
    since = main.compute_weekly_since(tmp_db, now=now)
    assert since == "2026-08-13"


def test_since_explicito_siempre_gana_en_weekly(tmp_path, monkeypatch):
    """run_pipeline no debe recalcular since cuando se pasó uno explícito,
    ni siquiera en modo weekly."""
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    monkeypatch.setattr(main.db, "connect", fake_connect)
    monkeypatch.setattr(main, "SCRAPERS", [])

    result = main.run_pipeline("weekly", "2026-02-01")
    assert result["raw"] == 0

    conn = fake_connect()
    row = conn.execute(
        "SELECT since FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row["since"] == "2026-02-01"
    conn.close()


def test_weekly_sin_since_lo_calcula_en_vez_de_dejarlo_none(tmp_path, monkeypatch):
    """Regresión del hallazgo Important #1: since=None en weekly hacía que
    DataForSEO cayera a BACKFILL_SINCE y el filtro de fecha de Instagram
    se desactivara. run_pipeline debe grabar un since concreto, nunca NULL."""
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    monkeypatch.setattr(main.db, "connect", fake_connect)
    monkeypatch.setattr(main, "SCRAPERS", [])

    main.run_pipeline("weekly", None)

    conn = fake_connect()
    row = conn.execute(
        "SELECT since FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row["since"] is not None
    conn.close()


def test_run_pipeline_sin_brand_usa_avianca_por_default(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    monkeypatch.setattr(main.db, "connect", fake_connect)
    monkeypatch.setattr(main, "SCRAPERS", [])

    main.run_pipeline("weekly", "2026-02-01")

    conn = fake_connect()
    row = conn.execute(
        "SELECT brand FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row["brand"] == "Avianca"
    conn.close()


def test_run_pipeline_con_brand_explicito_lo_registra_en_runs_y_lo_pasa_a_los_scrapers(
    tmp_path, monkeypatch,
):
    """--brand debe: (a) quedar registrado en runs.brand, y (b) pasarse
    como perfil completo a cada scraper (Tarea 4) — no un default fijo
    resuelto al importar."""
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    perfiles_recibidos = []

    def fake_scraper(brand, since=None):
        perfiles_recibidos.append(brand)
        return []

    monkeypatch.setattr(main.db, "connect", fake_connect)
    monkeypatch.setattr(main, "SCRAPERS", [("Fake", fake_scraper)])

    main.run_pipeline("weekly", "2026-02-01", brand_name="LATAM")

    conn = fake_connect()
    row = conn.execute(
        "SELECT brand FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row["brand"] == "LATAM"
    conn.close()

    assert len(perfiles_recibidos) == 1
    assert perfiles_recibidos[0]["name"] == "LATAM"
    assert perfiles_recibidos[0]["keyword"] == "LATAM"


def test_run_pipeline_marca_desconocida_falla_con_mensaje_claro(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    monkeypatch.setattr(main.db, "connect", fake_connect)
    monkeypatch.setattr(main, "SCRAPERS", [])

    try:
        main.run_pipeline("weekly", "2026-02-01", brand_name="Delta")
        assert False, "debía lanzar ValueError"
    except ValueError as e:
        assert "Delta" in str(e)


# ── --solo-instagram (muestras comparables: re-correr solo Instagram) ────

def test_run_pipeline_con_scrapers_explicito_ignora_los_demas(tmp_path, monkeypatch):
    """run_pipeline(scrapers=[...]) debe usar SOLO esa lista, no el
    SCRAPERS completo del módulo — así --solo-instagram no dispara
    DataForSEO ni TikTok."""
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    llamados = []

    def fake_web(brand, since=None):
        llamados.append("web")
        return []

    def fake_instagram(brand, since=None):
        llamados.append("instagram")
        return []

    monkeypatch.setattr(main.db, "connect", fake_connect)
    # SCRAPERS completo trae "web" — si run_pipeline lo usara en vez del
    # subconjunto pasado, "web" aparecería en `llamados`.
    monkeypatch.setattr(main, "SCRAPERS", [("Web", fake_web), ("Instagram", fake_instagram)])

    main.run_pipeline("weekly", "2026-01-01", scrapers=[("Instagram", fake_instagram)])

    assert llamados == ["instagram"]


def test_cli_solo_instagram_pasa_solo_instagram_a_run_pipeline(monkeypatch):
    """La flag --solo-instagram debe acotar run_pipeline() a
    [('Instagram', apify_instagram.scrape)] — nada de DataForSEO ni TikTok."""
    llamada = {}

    def fake_run_pipeline(mode, since, brand_name=main.DEFAULT_BRAND, scrapers=None):
        llamada["mode"] = mode
        llamada["since"] = since
        llamada["brand_name"] = brand_name
        llamada["scrapers"] = scrapers
        return {}

    monkeypatch.setattr(main, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--solo-instagram", "--since", "2026-01-01", "--brand", "LATAM"],
    )

    main.main()

    assert llamada["since"] == "2026-01-01"
    assert llamada["brand_name"] == "LATAM"
    assert llamada["scrapers"] == [("Instagram", apify_instagram.scrape)]


# ── Cambio 1 (retiro del canal web): DataForSEO fuera del pipeline activo ──

def test_scrapers_por_defecto_ya_no_incluye_dataforseo():
    """El canal web se retiró del pipeline activo (Cambio 1) — SCRAPERS
    debe traer solo Instagram y TikTok, en ese orden, sin DataForSEO ni
    ningún otro scraper web. scrapers/dataforseo_scraper.py se conserva
    (ver su docstring) pero no debe estar cableado aquí."""
    nombres = [nombre for nombre, _ in main.SCRAPERS]
    assert nombres == ["Instagram", "TikTok"]
    assert "DataForSEO" not in nombres


def test_cli_retirar_canal_web_llama_al_modulo_correcto(monkeypatch, tmp_path):
    """--retirar-canal-web debe invocar pipeline.web_channel_retirement.run
    con la conexión y la marca pedida — no gasta ninguna API."""
    db_file = tmp_path / "test.db"

    def fake_connect(path=None):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        store_db.init_db(conn)
        return conn

    llamada = {}

    def fake_run(conn, brand=None):
        llamada["brand"] = brand
        return {"evaluated": 0, "marked": 0, "already_marked": 0}

    monkeypatch.setattr(main.db, "connect", fake_connect)
    monkeypatch.setattr(main.web_channel_retirement, "run", fake_run)
    monkeypatch.setattr(
        "sys.argv", ["main.py", "--retirar-canal-web", "--brand", "LATAM"],
    )

    main.main()

    assert llamada["brand"] == "LATAM"
