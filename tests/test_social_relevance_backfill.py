"""
pipeline/social_relevance_backfill.py: aplica retroactivamente el filtro
de hashtag (pipeline/relevance.py, Tarea 1/2) a menciones de TikTok ya
guardadas — sin gastar API, sin borrar filas.
"""
from pipeline import social_relevance_backfill
from store import db

MEME_LATAM = (
    "Usssshhhh es que nunca vienen a otro lugar que no sea Brasil,MEXICO "
    "#latam #kpop #dahyun @TWICE"
)
RESENA_VUELO_PT = (
    "Como foi minha experiência voando com a latam (Melhor que a Gol) "
    "#latam #latamairlines"
)


def _mention(idx, platform="tiktok", text=MEME_LATAM, author="user",
             brand="LATAM", **kw):
    base = {
        "id": f"m-{idx}",
        "platform": platform,
        "source_url": f"https://tiktok.com/{idx}",
        "text": text,
        "author": author,
        "brand": brand,
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10, "shares": 1, "comments_count": 2,
        "classification_status": "unclassified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_excluye_meme_de_hashtag_sin_contexto_aeronautico(tmp_db):
    _seed(tmp_db, [_mention(1, text=MEME_LATAM)])

    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res["evaluated"] == 1
    assert res["excluded"] == 1
    assert res["restored"] == 0
    assert res["reasons"] == {"sin_contexto_aeronautico": 1}

    fila = db.all_mentions(tmp_db)[0]
    assert fila["exclusion_reason"] == "sin_contexto_aeronautico"


def test_conserva_resena_de_vuelo_sin_marcarla(tmp_db):
    _seed(tmp_db, [_mention(1, text=RESENA_VUELO_PT)])

    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res["excluded"] == 0
    fila = db.all_mentions(tmp_db)[0]
    assert fila["exclusion_reason"] is None


def test_cuenta_oficial_nunca_se_excluye(tmp_db):
    """Un video de la cuenta oficial (latam_colombia) es relevante aunque
    el texto sea un meme sin contexto aeronáutico — el mismo argumento que
    exime a los comentarios de posts propios."""
    _seed(tmp_db, [_mention(1, text="Feliz viernes a todos", author="latam_colombia")])

    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res["excluded"] == 0
    fila = db.all_mentions(tmp_db)[0]
    assert fila["exclusion_reason"] is None


def test_no_toca_plataformas_que_no_son_tiktok(tmp_db):
    """Instagram (comentarios de post propio) nunca pasa por este filtro
    — ver pipeline/relevance.py."""
    _seed(tmp_db, [_mention(1, platform="instagram", text=MEME_LATAM)])

    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res == {"evaluated": 0, "excluded": 0, "restored": 0, "reasons": {}}
    fila = db.all_mentions(tmp_db)[0]
    assert fila["exclusion_reason"] is None


def test_es_reversible_al_recorrer_tras_recalibrar(tmp_db, monkeypatch):
    """Si la regla se recalibra (p.ej. se agrega una palabra de contexto
    nueva) y una fila que antes se excluyó ahora sí pasa, re-correr el
    backfill la reincluye automáticamente — no hace falta un modo aparte
    para deshacer."""
    _seed(tmp_db, [_mention(1, text=MEME_LATAM)])
    social_relevance_backfill.run(tmp_db, brand="LATAM")
    assert db.all_mentions(tmp_db)[0]["exclusion_reason"] == "sin_contexto_aeronautico"

    def fake_is_relevant(mention, brand):
        return True, ""

    monkeypatch.setattr(social_relevance_backfill, "is_relevant", fake_is_relevant)
    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res["restored"] == 1
    assert db.all_mentions(tmp_db)[0]["exclusion_reason"] is None


def test_no_reescribe_la_fila_si_la_razon_no_cambio(tmp_db, monkeypatch):
    """Segunda corrida sin cambios no debe volver a escribir la columna —
    verificado interceptando set_exclusion_reason."""
    _seed(tmp_db, [_mention(1, text=MEME_LATAM)])
    social_relevance_backfill.run(tmp_db, brand="LATAM")

    llamadas = []
    original = db.set_exclusion_reason

    def spy(conn, mention_id, reason):
        llamadas.append((mention_id, reason))
        return original(conn, mention_id, reason)

    monkeypatch.setattr(db, "set_exclusion_reason", spy)
    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res["excluded"] == 1
    assert llamadas == []


def test_acotado_por_marca_no_toca_la_otra(tmp_db):
    _seed(tmp_db, [
        _mention(1, text=MEME_LATAM, brand="LATAM"),
        _mention(2, text="Un video cualquiera sin relación", brand="Avianca"),
    ])

    res = social_relevance_backfill.run(tmp_db, brand="LATAM")

    assert res["evaluated"] == 1
    filas = {f["id"]: f for f in db.all_mentions(tmp_db)}
    assert filas["m-1"]["exclusion_reason"] == "sin_contexto_aeronautico"
    assert filas["m-2"]["exclusion_reason"] is None  # Avianca no se tocó


def test_sin_marca_recorre_todas(tmp_db):
    _seed(tmp_db, [
        _mention(1, text=MEME_LATAM, brand="LATAM"),
        _mention(2, text="Un video cualquiera sin relación", brand="Avianca"),
    ])

    res = social_relevance_backfill.run(tmp_db)

    assert res["evaluated"] == 2
    filas = {f["id"]: f for f in db.all_mentions(tmp_db)}
    assert filas["m-1"]["exclusion_reason"] == "sin_contexto_aeronautico"
    assert filas["m-2"]["exclusion_reason"] == "sin_keyword"


def test_sin_menciones_de_tiktok_no_falla(tmp_db):
    _seed(tmp_db, [_mention(1, platform="instagram", text=MEME_LATAM)])

    res = social_relevance_backfill.run(tmp_db)

    assert res == {"evaluated": 0, "excluded": 0, "restored": 0, "reasons": {}}
