"""
pipeline/source_account_backfill.py: la orquestación (leer postUrl de la
DB, pedir Fase 1, escribir source_account) se prueba con fetch_fn
inyectado — ningún test golpea Apify.
"""
from pipeline import source_account_backfill
from store import db


def _mention(idx, post_url, brand=None, source_account=None, **kw):
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
    if brand is not None:
        base["brand"] = brand
    if source_account is not None:
        base["source_account"] = source_account
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_enriquece_menciones_con_la_cuenta_del_post(tmp_db):
    _seed(tmp_db, [
        _mention(1, "https://www.instagram.com/p/ABC/"),
        _mention(2, "https://www.instagram.com/p/ABC/"),
    ])

    def fake_fetch(urls):
        assert urls == ["https://www.instagram.com/p/ABC/"]
        return {"https://www.instagram.com/p/ABC/": {
            "views": None, "likes": 10, "comments": 2, "owner_username": "latamairlines_colombia"}}

    res = source_account_backfill.run(tmp_db, fetch_fn=fake_fetch)

    assert res == {
        "posts_requested": 1, "posts_found": 1,
        "mentions_enriched": 2, "mentions_without_owner": 0,
    }
    for fila in db.all_mentions(tmp_db):
        assert fila["source_account"] == "latamairlines_colombia"


def test_no_toca_menciones_que_ya_tienen_source_account(tmp_db):
    """Filas ya pobladas (p.ej. por una corrida con el scraper nuevo) no
    deben volver a pedirse — ni siquiera cuentan en post_urls."""
    _seed(tmp_db, [
        _mention(1, "https://www.instagram.com/p/YA-TIENE/", source_account="avianca"),
    ])

    pedidos = []

    def fake_fetch(urls):
        pedidos.append(urls)
        return {}

    res = source_account_backfill.run(tmp_db, fetch_fn=fake_fetch)

    assert pedidos == []
    assert res == {"posts_requested": 0, "posts_found": 0,
                    "mentions_enriched": 0, "mentions_without_owner": 0}
    assert db.all_mentions(tmp_db)[0]["source_account"] == "avianca"


def test_post_sin_owner_username_no_falla(tmp_db):
    """El actor no devolvió ownerUsername para ese post (caso borde) — la
    mención queda sin source_account, no con un valor inventado."""
    _seed(tmp_db, [_mention(1, "https://www.instagram.com/p/SIN-OWNER/")])

    def fake_fetch(urls):
        return {"https://www.instagram.com/p/SIN-OWNER/": {
            "views": None, "likes": 0, "comments": 0, "owner_username": None}}

    res = source_account_backfill.run(tmp_db, fetch_fn=fake_fetch)

    assert res["mentions_enriched"] == 0
    assert res["mentions_without_owner"] == 1
    assert db.all_mentions(tmp_db)[0]["source_account"] is None


def test_post_url_no_encontrado_en_el_mapa_no_falla(tmp_db):
    _seed(tmp_db, [_mention(1, "https://www.instagram.com/p/BORRADO/")])

    res = source_account_backfill.run(tmp_db, fetch_fn=lambda urls: {})

    assert res["mentions_enriched"] == 0
    assert res["mentions_without_owner"] == 1


def test_deduplica_post_urls_antes_de_pedir_fase_1(tmp_db):
    _seed(tmp_db, [
        _mention(1, "https://www.instagram.com/p/A/"),
        _mention(2, "https://www.instagram.com/p/A/"),
        _mention(3, "https://www.instagram.com/p/B/"),
    ])
    pedidos = []

    def fake_fetch(urls):
        pedidos.append(urls)
        return {}

    source_account_backfill.run(tmp_db, fetch_fn=fake_fetch)

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

    res = source_account_backfill.run(tmp_db, fetch_fn=lambda urls: {})

    assert res == {"posts_requested": 0, "posts_found": 0,
                    "mentions_enriched": 0, "mentions_without_owner": 0}


def test_acotado_por_marca_no_pide_posts_de_otra_marca(tmp_db):
    """run(conn, brand='LATAM') no debe pedir ni tocar posts de Avianca —
    a diferencia de instagram_reach_backfill.run(), que no filtra por
    marca (hallazgo de .superpowers/latam-backfill.md §5)."""
    _seed(tmp_db, [
        _mention(1, "https://www.instagram.com/p/AVIANCA1/", brand="Avianca"),
        _mention(2, "https://www.instagram.com/p/LATAM1/", brand="LATAM"),
    ])
    pedidos = []

    def fake_fetch(urls):
        pedidos.append(urls)
        return {"https://www.instagram.com/p/LATAM1/": {
            "views": None, "likes": 0, "comments": 0, "owner_username": "latamairlines"}}

    res = source_account_backfill.run(tmp_db, brand="LATAM", fetch_fn=fake_fetch)

    assert pedidos == [["https://www.instagram.com/p/LATAM1/"]]
    assert res["mentions_enriched"] == 1
    filas = {f["id"]: f for f in db.all_mentions(tmp_db)}
    assert filas["m-2"]["source_account"] == "latamairlines"
    assert filas["m-1"]["source_account"] is None  # Avianca no se tocó


def test_es_idempotente_en_la_escritura(tmp_db):
    _seed(tmp_db, [_mention(1, "https://www.instagram.com/p/ABC/")])

    def fake_fetch(urls):
        return {"https://www.instagram.com/p/ABC/": {
            "views": None, "likes": 1, "comments": 1, "owner_username": "avianca"}}

    source_account_backfill.run(tmp_db, fetch_fn=fake_fetch)
    source_account_backfill.run(tmp_db, fetch_fn=fake_fetch)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["source_account"] == "avianca"
    assert len(db.all_mentions(tmp_db)) == 1
