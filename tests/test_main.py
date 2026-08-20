"""
Tests del cálculo de `since` para la corrida `weekly` (main.py).

Ningún test golpea una API: run_pipeline se ejerce con SCRAPERS
monkeypateado a vacío y sin menciones pendientes de clasificar, así que
classify_pending.run() retorna de inmediato sin llamar a DeepSeek.
"""
import sqlite3
from datetime import datetime, timezone

import main
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
