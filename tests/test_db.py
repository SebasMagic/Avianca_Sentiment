from store import db


def _mention(text="Avianca me perdió la maleta en Bogotá",
             url="https://x.com/1", mid="m-1",
             fetched_at="2026-08-19T00:00:00+00:00"):
    return {
        "id": mid,
        "platform": "tiktok",
        "source_url": url,
        "text": text,
        "author": "usuario1",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10,
        "shares": 2,
        "comments_count": 3,
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.0,
        "sentiment_neutral": 1.0,
        "emotion": "neutral",
        "is_complaint": 0,
        "complaint_driver": None,
        "classification_status": "unclassified",
        "raw": {"foo": "bar"},
        "fetched_at": fetched_at,
    }


def test_fingerprint_es_estable_y_ignora_id():
    a = db.fingerprint("tiktok", "https://x.com/1", "hola mundo")
    b = db.fingerprint("tiktok", "https://x.com/1", "hola mundo")
    assert a == b
    assert len(a) == 64


def test_fingerprint_distingue_texto_distinto_en_misma_url():
    a = db.fingerprint("tiktok", "https://x.com/1", "hola mundo")
    b = db.fingerprint("tiktok", "https://x.com/1", "otro comentario distinto")
    assert a != b


def test_insertar_menciones_nuevas(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert (ins, dup) == (1, 0)
    assert len(db.all_mentions(tmp_db)) == 1


def test_reinsertar_el_mismo_lote_es_idempotente(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    run_2 = db.start_run(tmp_db, "weekly", None)
    ins, dup = db.upsert_mentions(tmp_db, [_mention()], run_2)
    assert (ins, dup) == (0, 1)
    assert len(db.all_mentions(tmp_db)) == 1


def test_run_id_conserva_la_primera_corrida(tmp_db):
    """INSERT OR IGNORE preserva run_id y fetched_at de la primera corrida."""
    run_1 = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(fetched_at="2026-08-19T10:00:00+00:00")], run_1)

    run_2 = db.start_run(tmp_db, "weekly", None)
    db.upsert_mentions(tmp_db, [_mention(fetched_at="2026-08-20T15:30:00+00:00")], run_2)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["run_id"] == run_1
    assert fila["fetched_at"] == "2026-08-19T10:00:00+00:00"


def test_mismo_url_distinto_texto_si_inserta(tmp_db):
    """Dos comentarios distintos pueden vivir en la misma URL — por eso el
    dedup va por fingerprint del contenido y no por source_url."""
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(mid="m-1"),
            _mention(mid="m-2", text="Otro comentario totalmente diferente aquí"),
        ],
        run_id,
    )
    assert (ins, dup) == (2, 0)
    assert len(db.all_mentions(tmp_db)) == 2


def test_fingerprint_colision_regresion_prefijo_largo(tmp_db):
    """Regresión: dos comentarios en misma URL con prefijo largo (>80 chars)
    que divergen solo al final, deben tener fingerprints distintos y ambos insertarse.

    Antes del fix, fingerprint truncaba a 80 chars, causando una colisión falsa."""
    run_id = db.start_run(tmp_db, "seed", None)

    # Textos que comparten un prefijo muy largo, divergen solo al final
    prefix = "Avianca canceló mi vuelo y no me han dado respuesta desde hace más de una semana ya " * 2
    text1 = prefix + "esto es inaceptable"
    text2 = prefix + "solicito reembolso inmediato"

    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(mid="m-1", text=text1),
            _mention(mid="m-2", text=text2),
        ],
        run_id,
    )

    # Ambos deben insertarse, NO debe haber duplicado falso
    assert (ins, dup) == (2, 0), f"expected (2, 0) but got ({ins}, {dup})"
    assert len(db.all_mentions(tmp_db)) == 2


def test_pending_classification_devuelve_solo_unclassified(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    pendientes = db.pending_classification(tmp_db)
    assert len(pendientes) == 1

    db.update_classification(tmp_db, pendientes[0]["id"], {
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.9,
        "sentiment_neutral": 0.1,
        "emotion": "anger",
        "is_complaint": True,
        "complaint_driver": "equipaje",
    })

    assert db.pending_classification(tmp_db) == []
    fila = db.all_mentions(tmp_db)[0]
    assert fila["complaint_driver"] == "equipaje"
    assert fila["classification_status"] == "classified"
    assert fila["is_complaint"] == 1


def test_raw_se_guarda_y_recupera_como_dict(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert db.all_mentions(tmp_db)[0]["raw"] == {"foo": "bar"}


def test_finish_run_guarda_contadores(tmp_db):
    run_id = db.start_run(tmp_db, "backfill", "2026-04-19")
    db.finish_run(tmp_db, run_id, raw_count=10, filtered_count=3,
                  inserted_count=2, duplicate_count=1, notes="ok - backfill complete")
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["raw_count"] == 10
    assert fila["filtered_count"] == 3
    assert fila["inserted_count"] == 2
    assert fila["duplicate_count"] == 1
    assert fila["notes"] == "ok - backfill complete"
    assert fila["since"] == "2026-04-19"
    assert fila["finished_at"] is not None
