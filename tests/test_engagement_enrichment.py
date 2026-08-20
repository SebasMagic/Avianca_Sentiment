"""
pipeline/engagement_enrichment.py no golpea ninguna API: solo relee el
`raw` que ya está en la DB y puebla saves/views/reach_source (Tarea 1 del
desglose de engagement). Fixtures tomadas de items reales verificados
contra data/avianca.db (ver docstring del módulo).
"""
from pipeline import engagement_enrichment
from store import db


def _mention(idx, platform, raw, **kw):
    base = {
        "id": f"m-{idx}",
        "platform": platform,
        "source_url": f"https://x.com/{idx}",
        "text": f"Avianca comentario numero {idx} sobre el servicio",
        "author": f"user{idx}",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 0, "shares": 0, "comments_count": 0,
        "classification_status": "unclassified",
        "raw": raw, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


TIKTOK_RAW = {
    "diggCount": 1961,
    "commentCount": 55,
    "shareCount": 200,
    "collectCount": 249,
    "playCount": 61500,
    "repostCount": 0,
}

INSTAGRAM_RAW = {
    "postUrl": "https://www.instagram.com/p/DbEIKJTFTcf/",
    "commentUrl": "https://www.instagram.com/p/DbEIKJTFTcf/c/18102936407183474",
    "id": "18102936407183474",
    "text": "@aeromexico",
    "ownerUsername": "abyhoplab",
    "timestamp": "2026-07-29T21:44:25.000Z",
    "repliesCount": None,
    "likesCount": 7,
}

SEED_RAW = {"origen": "seed_excel_v1"}


def test_mapeo_tiktok_completo(tmp_db):
    """Los seis campos de un video de TikTok se mapean a las columnas
    correctas — caso real verificado contra data/avianca.db."""
    _seed(tmp_db, [_mention(1, "tiktok", TIKTOK_RAW)])

    res = engagement_enrichment.run(tmp_db)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["likes"] == 1961
    assert fila["comments_count"] == 55
    assert fila["shares"] == 200
    assert fila["saves"] == 249
    assert fila["views"] == 61500
    assert fila["reach_source"] == "propio"
    assert res == {"enriched": 1, "skipped": 0, "by_platform": {"tiktok": 1}}


def test_mapeo_instagram_solo_likes(tmp_db):
    """Instagram solo aporta likesCount del comentario — shares/comments_count/
    saves NO se tocan (un comentario no los tiene)."""
    _seed(tmp_db, [_mention(1, "instagram", INSTAGRAM_RAW, likes=0, shares=0, comments_count=0)])

    engagement_enrichment.run(tmp_db)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["likes"] == 7
    assert fila["shares"] == 0        # sin tocar, tal cual estaba
    assert fila["comments_count"] == 0  # sin tocar
    assert fila["saves"] is None      # nunca se pobló — ausencia, no cero
    assert fila["views"] is None
    assert fila["reach_source"] is None


def test_filas_sin_raw_completo_quedan_null_no_cero(tmp_db):
    """El seed del Excel v1 (raw={'origen': 'seed_excel_v1'}) no trae los
    campos esperados — la fila queda intacta, con saves/views en NULL."""
    _seed(tmp_db, [_mention(1, "tiktok", SEED_RAW)])

    res = engagement_enrichment.run(tmp_db)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["saves"] is None
    assert fila["views"] is None
    assert fila["reach_source"] is None
    assert res == {"enriched": 0, "skipped": 1, "by_platform": {}}


def test_plataforma_web_no_tiene_mapeo_queda_intacta(tmp_db):
    _seed(tmp_db, [_mention(1, "web", {"origen": "dataforseo"})])

    res = engagement_enrichment.run(tmp_db)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["saves"] is None
    assert fila["views"] is None
    assert res["skipped"] == 1


def test_es_idempotente(tmp_db):
    """Correrlo dos veces con el mismo raw da el mismo resultado — nunca
    acumula ni suma sobre el valor anterior."""
    _seed(tmp_db, [_mention(1, "tiktok", TIKTOK_RAW)])

    engagement_enrichment.run(tmp_db)
    engagement_enrichment.run(tmp_db)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["saves"] == 249
    assert fila["views"] == 61500
    assert len(db.all_mentions(tmp_db)) == 1


def test_playcount_ausente_en_tiktok_no_inventa_reach_source(tmp_db):
    """Un item de TikTok con diggCount pero sin playCount (caso hipotético,
    p.ej. una versión de actor que no lo trae) no debe marcar reach_source
    'propio' sin tener el número — views y reach_source quedan NULL."""
    raw_sin_views = {k: v for k, v in TIKTOK_RAW.items() if k != "playCount"}
    _seed(tmp_db, [_mention(1, "tiktok", raw_sin_views)])

    engagement_enrichment.run(tmp_db)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["saves"] == 249       # el resto del mapeo sí aplica
    assert fila["views"] is None
    assert fila["reach_source"] is None


def test_reporta_conteo_por_plataforma(tmp_db):
    _seed(tmp_db, [
        _mention(1, "tiktok", TIKTOK_RAW),
        _mention(2, "tiktok", TIKTOK_RAW),
        _mention(3, "instagram", INSTAGRAM_RAW),
    ])

    res = engagement_enrichment.run(tmp_db)

    assert res["by_platform"] == {"tiktok": 2, "instagram": 1}
    assert res["enriched"] == 3
