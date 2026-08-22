"""store.db.latest_completed_run — usado por dashboard/ai_visibility_aggregate.py
para agrupar las filas de la captura más reciente por run_id (ver docstring
de la función: captured_at no sirve para esto, varía fila a fila dentro
de una misma corrida de prompts)."""
from store import db


def test_devuelve_la_corrida_mas_reciente_por_marca_y_modo(tmp_db):
    r1 = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    tmp_db.execute("UPDATE runs SET started_at = ? WHERE id = ?",
                    ("2026-01-01T00:00:00+00:00", r1))
    db.finish_run(tmp_db, r1, 1, 1, 1, 0)

    r2 = db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")
    tmp_db.execute("UPDATE runs SET started_at = ? WHERE id = ?",
                    ("2026-02-01T00:00:00+00:00", r2))
    db.finish_run(tmp_db, r2, 2, 2, 2, 0)

    resultado = db.latest_completed_run(tmp_db, "Avianca", "ai_visibility")
    assert resultado["id"] == r2


def test_ignora_corridas_de_otra_marca_o_de_otro_modo(tmp_db):
    r_latam = db.start_run(tmp_db, "ai_visibility", None, brand="LATAM")
    db.finish_run(tmp_db, r_latam, 1, 1, 1, 0)
    r_otro_modo = db.start_run(tmp_db, "weekly", None, brand="Avianca")
    db.finish_run(tmp_db, r_otro_modo, 1, 1, 1, 0)

    assert db.latest_completed_run(tmp_db, "Avianca", "ai_visibility") is None


def test_ignora_corridas_sin_terminar(tmp_db):
    db.start_run(tmp_db, "ai_visibility", None, brand="Avianca")  # nunca se termina
    assert db.latest_completed_run(tmp_db, "Avianca", "ai_visibility") is None


def test_sin_ninguna_corrida_devuelve_none(tmp_db):
    assert db.latest_completed_run(tmp_db, "Avianca", "ai_visibility") is None
