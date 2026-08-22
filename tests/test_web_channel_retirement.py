"""
pipeline/web_channel_retirement.py: marca TODAS las menciones platform='web'
ya guardadas como excluidas (Cambio 1, retiro del canal web) — sin gastar
API, sin borrar filas, idéntico tratamiento que el filtro de relevancia
social pero SIN evaluar el contenido (decisión de política, no una regla
caso por caso).
"""
from config import WEB_CHANNEL_RETIREMENT_REASON
from pipeline import web_channel_retirement
from store import db


def _mention(idx, platform="web", brand="Avianca", author="dominio.com", **kw):
    base = {
        "id": f"m-{idx}",
        "platform": platform,
        "source_url": f"https://x.com/{idx}",
        "text": f"texto {idx}",
        "author": author,
        "brand": brand,
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 0, "shares": 0, "comments_count": 0,
        "classification_status": "unclassified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_marca_todas_las_menciones_web(tmp_db):
    _seed(tmp_db, [_mention(1), _mention(2, author="otrodominio.com")])

    res = web_channel_retirement.run(tmp_db, brand="Avianca")

    assert res == {"evaluated": 2, "marked": 2, "already_marked": 0}
    filas = db.all_mentions(tmp_db)
    assert all(f["exclusion_reason"] == WEB_CHANNEL_RETIREMENT_REASON for f in filas)


def test_no_toca_plataformas_que_no_son_web(tmp_db):
    _seed(tmp_db, [_mention(1, platform="tiktok", author="user")])

    res = web_channel_retirement.run(tmp_db, brand="Avianca")

    assert res == {"evaluated": 0, "marked": 0, "already_marked": 0}
    assert db.all_mentions(tmp_db)[0]["exclusion_reason"] is None


def test_no_borra_ninguna_fila(tmp_db):
    """La migración preserva filas: el conteo total antes y después del
    retiro es idéntico, tanto para las web (marcadas) como para las
    demás (intactas)."""
    _seed(tmp_db, [
        _mention(1, platform="web"),
        _mention(2, platform="tiktok", author="user"),
        _mention(3, platform="instagram", author="user2"),
    ])
    antes = len(db.all_mentions(tmp_db))

    web_channel_retirement.run(tmp_db, brand="Avianca")

    despues = len(db.all_mentions(tmp_db))
    assert despues == antes == 3


def test_es_idempotente(tmp_db):
    """Correrlo dos veces no vuelve a contar lo ya marcado como 'marcado
    ahora' — la segunda corrida reporta already_marked, no marked."""
    _seed(tmp_db, [_mention(1)])
    web_channel_retirement.run(tmp_db, brand="Avianca")

    res = web_channel_retirement.run(tmp_db, brand="Avianca")
    assert res == {"evaluated": 1, "marked": 0, "already_marked": 1}


def test_no_reescribe_la_fila_si_ya_estaba_marcada(tmp_db, monkeypatch):
    """Segunda corrida sin cambios no debe volver a escribir la columna —
    verificado interceptando set_exclusion_reason (mismo patrón que
    tests/test_social_relevance_backfill.py)."""
    _seed(tmp_db, [_mention(1)])
    web_channel_retirement.run(tmp_db, brand="Avianca")

    llamadas = []
    original = db.set_exclusion_reason

    def spy(conn, mention_id, reason):
        llamadas.append((mention_id, reason))
        return original(conn, mention_id, reason)

    monkeypatch.setattr(db, "set_exclusion_reason", spy)
    web_channel_retirement.run(tmp_db, brand="Avianca")

    assert llamadas == []


def test_acotado_por_marca_no_toca_la_otra(tmp_db):
    _seed(tmp_db, [
        _mention(1, brand="Avianca"),
        _mention(2, brand="LATAM", author="otro.com"),
    ])

    res = web_channel_retirement.run(tmp_db, brand="Avianca")

    assert res["evaluated"] == 1
    filas = {f["id"]: f for f in db.all_mentions(tmp_db)}
    assert filas["m-1"]["exclusion_reason"] == WEB_CHANNEL_RETIREMENT_REASON
    assert filas["m-2"]["exclusion_reason"] is None  # LATAM no se tocó


def test_sin_marca_recorre_todas(tmp_db):
    _seed(tmp_db, [
        _mention(1, brand="Avianca"),
        _mention(2, brand="LATAM", author="otro.com"),
    ])

    res = web_channel_retirement.run(tmp_db)

    assert res["evaluated"] == 2
    filas = db.all_mentions(tmp_db)
    assert all(f["exclusion_reason"] == WEB_CHANNEL_RETIREMENT_REASON for f in filas)


def test_sin_menciones_web_no_falla(tmp_db):
    _seed(tmp_db, [_mention(1, platform="tiktok", author="user")])

    res = web_channel_retirement.run(tmp_db)

    assert res == {"evaluated": 0, "marked": 0, "already_marked": 0}
