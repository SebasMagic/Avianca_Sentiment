"""
pipeline/instagram_reach_backfill.py: la orquestación (leer postUrl de la
DB, pedir Fase 1, escribir views/reach_source) se prueba con fetch_fn
inyectado — ningún test golpea Apify.
"""
from pipeline import instagram_reach_backfill
from store import db


def _mention(idx, post_url, **kw):
    base = {
        "id": f"m-{idx}",
        "platform": "instagram",
        "source_url": f"{post_url}#comment-{idx}",
        "text": f"comentario numero {idx}",
        "author": f"user{idx}",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 1, "shares": 0, "comments_count": 0,
        "classification_status": "unclassified",
        "raw": {"postUrl": post_url}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_enriquece_comentarios_con_views_del_post(tmp_db):
    _seed(tmp_db, [
        _mention(1, "https://www.instagram.com/p/ABC/"),
        _mention(2, "https://www.instagram.com/p/ABC/"),
    ])

    def fake_fetch(urls):
        assert urls == ["https://www.instagram.com/p/ABC/"]
        return {"https://www.instagram.com/p/ABC/": {"views": 32600, "likes": 1241, "comments": 31}}

    res = instagram_reach_backfill.run(tmp_db, fetch_fn=fake_fetch)

    assert res == {
        "posts_requested": 1, "posts_found": 1,
        "comments_enriched": 2, "comments_without_views": 0,
    }
    for fila in db.all_mentions(tmp_db):
        assert fila["views"] == 32600
        assert fila["reach_source"] == "post"


def test_post_sin_views_no_marca_reach_source(tmp_db):
    """Un post Sidecar sin video no aporta views — el comentario queda sin
    reach_source, no con 'post' apuntando a un valor inventado."""
    _seed(tmp_db, [_mention(1, "https://www.instagram.com/p/SIDECAR/")])

    def fake_fetch(urls):
        return {"https://www.instagram.com/p/SIDECAR/": {"views": None, "likes": 500, "comments": 12}}

    res = instagram_reach_backfill.run(tmp_db, fetch_fn=fake_fetch)

    assert res["comments_enriched"] == 0
    assert res["comments_without_views"] == 1
    fila = db.all_mentions(tmp_db)[0]
    assert fila["views"] is None
    assert fila["reach_source"] is None


def test_post_url_no_encontrado_en_el_mapa_no_falla(tmp_db):
    """El actor no devolvió ese post (borrado, privado, etc.) — el
    comentario queda sin views, sin reventar."""
    _seed(tmp_db, [_mention(1, "https://www.instagram.com/p/BORRADO/")])

    res = instagram_reach_backfill.run(tmp_db, fetch_fn=lambda urls: {})

    assert res["comments_enriched"] == 0
    assert res["comments_without_views"] == 1


def test_deduplica_post_urls_antes_de_pedir_fase_1(tmp_db):
    """79 comentarios de 3 posts distintos deben pedir solo 3 URLs, no 79 —
    es la razón de ser de este comando (una llamada de Fase 1, no una por
    comentario)."""
    _seed(tmp_db, [
        _mention(1, "https://www.instagram.com/p/A/"),
        _mention(2, "https://www.instagram.com/p/A/"),
        _mention(3, "https://www.instagram.com/p/B/"),
    ])
    pedidos = []

    def fake_fetch(urls):
        pedidos.append(urls)
        return {}

    instagram_reach_backfill.run(tmp_db, fetch_fn=fake_fetch)

    assert pedidos == [sorted(["https://www.instagram.com/p/A/", "https://www.instagram.com/p/B/"])]


def test_plataformas_no_instagram_se_ignoran(tmp_db):
    _seed(tmp_db, [
        {
            "id": "m-tiktok", "platform": "tiktok",
            "source_url": "https://tiktok.com/1", "text": "video de tiktok",
            "author": "user_tk", "published_at": "2026-05-01T10:00:00+00:00",
            "date_confidence": "exact", "country": "CO",
            "likes": 0, "shares": 0, "comments_count": 0,
            "classification_status": "unclassified",
            "raw": {"postUrl": "https://www.instagram.com/p/NUNCA/"},
            "fetched_at": "2026-08-19T00:00:00+00:00",
        },
    ])

    res = instagram_reach_backfill.run(tmp_db, fetch_fn=lambda urls: {})

    # No hay menciones instagram -> ni siquiera se llama fetch_fn.
    assert res == {"posts_requested": 0, "posts_found": 0,
                    "comments_enriched": 0, "comments_without_views": 0}


def test_es_idempotente_en_la_escritura(tmp_db):
    _seed(tmp_db, [_mention(1, "https://www.instagram.com/p/ABC/")])

    def fake_fetch(urls):
        return {"https://www.instagram.com/p/ABC/": {"views": 100, "likes": 1, "comments": 1}}

    instagram_reach_backfill.run(tmp_db, fetch_fn=fake_fetch)
    instagram_reach_backfill.run(tmp_db, fetch_fn=fake_fetch)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["views"] == 100
    assert len(db.all_mentions(tmp_db)) == 1
