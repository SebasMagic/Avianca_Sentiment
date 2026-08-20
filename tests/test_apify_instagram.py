"""
scrapers/apify_instagram.py no golpea la API real en tests: se
monkeypatchea ApifyClient por un doble de prueba que sirve datasets fijos.
"""
import config
from config import get_brand
from scrapers import apify_instagram
from store import db

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")


class _FakeDataset:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return iter(self._items)


class _FakeActorHandle:
    def __init__(self, client):
        self._client = client

    def call(self, run_input):
        self._client.calls.append(run_input)
        if run_input["resultsType"] == "posts":
            return {"defaultDatasetId": "posts"}
        return {"defaultDatasetId": "comments"}


class FakeApifyClient:
    """Doble de ApifyClient: dos datasets fijos (posts, comentarios)."""

    def __init__(self, token, *, posts, comments):
        self._posts = posts
        self._comments = comments
        self.calls = []

    def actor(self, actor_id):
        return _FakeActorHandle(self)

    def dataset(self, dataset_id):
        return _FakeDataset(self._posts if dataset_id == "posts" else self._comments)


POSTS = [{"url": "https://www.instagram.com/p/ABC123/", "shortCode": "ABC123"}]


def test_usa_commentUrl_cuando_el_item_lo_trae(monkeypatch):
    """commentUrl es un permalink real que Instagram sí interpreta como
    ancla al comentario (verificado: 100% de las filas reales lo traen).
    Debe preferirse sobre la construcción manual con '#comment-'."""
    comments = [{
        "id": "18102936407183474",
        "text": "Vuelo cancelado, pésimo servicio",
        "ownerUsername": "usuario1",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/ABC123/",
        "commentUrl": "https://www.instagram.com/p/ABC123/c/18102936407183474",
        "likesCount": 3,
    }]
    fake_client = FakeApifyClient(None, posts=POSTS, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["source_url"] == "https://www.instagram.com/p/ABC123/c/18102936407183474"


def test_cae_a_construccion_manual_si_no_hay_commentUrl(monkeypatch):
    """Sin commentUrl (p.ej. versión vieja del actor), cae al fallback
    postUrl + '#comment-{id}'."""
    comments = [{
        "id": "999",
        "text": "Buen servicio, gracias",
        "ownerUsername": "usuario2",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/ABC123/",
        "likesCount": 1,
    }]
    fake_client = FakeApifyClient(None, posts=POSTS, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["source_url"] == "https://www.instagram.com/p/ABC123/#comment-999"


def test_sin_commentUrl_ni_id_cae_a_la_url_del_post(monkeypatch):
    comments = [{
        "id": None,
        "text": "Comentario sin id",
        "ownerUsername": "usuario3",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/ABC123/",
        "likesCount": 0,
    }]
    fake_client = FakeApifyClient(None, posts=POSTS, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["source_url"] == "https://www.instagram.com/p/ABC123/"


# ── Tarea 2: alcance del post adjuntado al comentario ────────────────────

def test_comentario_de_post_video_hereda_views_con_reach_source_post(monkeypatch):
    """Un post type='Video' trae videoPlayCount en Fase 1 — verificado con
    datos reales. Cada comentario que sale de ese post debe llevar esas
    views con reach_source='post' (alcance del CONTENEDOR, no propio)."""
    posts = [{
        "url": "https://www.instagram.com/p/ABC123/",
        "shortCode": "ABC123",
        "type": "Video",
        "videoPlayCount": 32600,
        "likesCount": 1241,
        "commentsCount": 31,
    }]
    comments = [{
        "id": "1", "text": "Vuelo cancelado otra vez",
        "ownerUsername": "usuario1",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/ABC123/",
        "commentUrl": "https://www.instagram.com/p/ABC123/c/1",
        "likesCount": 3,
    }]
    fake_client = FakeApifyClient(None, posts=posts, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["views"] == 32600
    assert results[0]["reach_source"] == "post"
    assert results[0]["likes"] == 3  # el like es del COMENTARIO, no se sobreescribe con el del post
    assert results[0]["saves"] is None  # un comentario no tiene saves propios


def test_comentario_de_post_sidecar_sin_video_no_tiene_views(monkeypatch):
    """Un post Sidecar (carrusel de imágenes) no trae videoPlayCount —
    verificado con datos reales: Instagram no expone reproducciones para
    contenido sin video. views y reach_source deben quedar None, nunca 0
    ni 'post' con un valor inventado."""
    posts = [{
        "url": "https://www.instagram.com/p/XYZ789/",
        "shortCode": "XYZ789",
        "type": "Sidecar",
        "likesCount": 500,
        "commentsCount": 12,
        # sin videoPlayCount — el ítem real tampoco lo trae
    }]
    comments = [{
        "id": "2", "text": "Qué lindas fotos",
        "ownerUsername": "usuario2",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/XYZ789/",
        "commentUrl": "https://www.instagram.com/p/XYZ789/c/2",
        "likesCount": 1,
    }]
    fake_client = FakeApifyClient(None, posts=posts, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["views"] is None
    assert results[0]["reach_source"] is None


def test_comentario_sin_post_correspondiente_en_el_mapa_no_falla(monkeypatch):
    """Si el postUrl del comentario no está en post_reach (caso borde: el
    actor devolvió el comentario pero no el post), views/reach_source
    quedan None en vez de reventar con un KeyError."""
    comments = [{
        "id": "3", "text": "comentario huérfano",
        "ownerUsername": "usuario3",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/NOEXISTE/",
        "commentUrl": "https://www.instagram.com/p/NOEXISTE/c/3",
        "likesCount": 0,
    }]
    fake_client = FakeApifyClient(None, posts=POSTS, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["views"] is None
    assert results[0]["reach_source"] is None


def test_post_reach_map_usa_campos_reales_de_fase_1():
    """_post_reach_map extrae exactamente views/likes/comments/owner_username
    de un item de post — fixture con los mismos nombres de clave verificados
    contra la API real (2026-08-20, perfil @avianca)."""
    posts = [
        {"url": "https://www.instagram.com/p/V1/", "type": "Video",
         "videoPlayCount": 100, "likesCount": 10, "commentsCount": 2,
         "ownerUsername": "avianca"},
        {"url": "https://www.instagram.com/p/S1/", "type": "Sidecar",
         "likesCount": 20, "commentsCount": 4, "ownerUsername": "avianca"},
        {"error": "no encontrado"},  # ítem de error del actor: se ignora
    ]
    reach = apify_instagram._post_reach_map(posts)

    assert reach["https://www.instagram.com/p/V1/"] == {
        "views": 100, "likes": 10, "comments": 2, "owner_username": "avianca"}
    assert reach["https://www.instagram.com/p/S1/"] == {
        "views": None, "likes": 20, "comments": 4, "owner_username": "avianca"}
    assert len(reach) == 2


def test_post_reach_map_sin_ownerUsername_deja_owner_username_none():
    """Un item de post que no trae 'ownerUsername' (caso borde) no debe
    reventar — owner_username queda None, no se inventa."""
    posts = [{"url": "https://www.instagram.com/p/V1/", "type": "Video",
              "videoPlayCount": 100, "likesCount": 10, "commentsCount": 2}]
    reach = apify_instagram._post_reach_map(posts)

    assert reach["https://www.instagram.com/p/V1/"]["owner_username"] is None


def test_fetch_post_reach_llama_fase_1_con_directUrls_de_posts(monkeypatch):
    """fetch_post_reach (usado por el backfill retroactivo, Tarea 2) pide
    resultsType='posts' con directUrls=post_urls específicos — no perfiles,
    no re-pide comentarios."""
    posts = [{"url": "https://www.instagram.com/p/V1/", "type": "Video",
              "videoPlayCount": 999, "likesCount": 5, "commentsCount": 1,
              "ownerUsername": "avianca"}]
    fake_client = FakeApifyClient(None, posts=posts, comments=[])
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    reach = apify_instagram.fetch_post_reach(["https://www.instagram.com/p/V1/"])

    assert reach == {"https://www.instagram.com/p/V1/": {
        "views": 999, "likes": 5, "comments": 1, "owner_username": "avianca"}}
    assert fake_client.calls[0]["resultsType"] == "posts"
    assert fake_client.calls[0]["directUrls"] == ["https://www.instagram.com/p/V1/"]


def test_fetch_post_reach_sin_urls_no_llama_al_actor(monkeypatch):
    fake_client = FakeApifyClient(None, posts=[], comments=[])
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    reach = apify_instagram.fetch_post_reach([])

    assert reach == {}
    assert fake_client.calls == []


# ── Tarea 4 (multi-marca): la Fase 1 usa los perfiles de la marca pasada ──

def test_scrape_usa_los_perfiles_de_instagram_de_la_marca_pasada(monkeypatch):
    """scrape() debe pedir la Fase 1 con los perfiles de LATAM cuando se le
    pasa el perfil de LATAM, no un default de Avianca resuelto al importar."""
    fake_client = FakeApifyClient(None, posts=POSTS, comments=[])
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    apify_instagram.scrape(LATAM)

    fase_1 = fake_client.calls[0]
    assert fase_1["resultsType"] == "posts"
    assert fase_1["directUrls"] == LATAM["instagram_profiles"]
    assert fase_1["directUrls"] != AVIANCA["instagram_profiles"]


# ── Registro de cuenta de origen (Tarea 1: muestras comparables) ─────────

def test_comentario_hereda_source_account_del_owner_username_del_post(monkeypatch):
    """Cada comentario debe llevar 'source_account' = la cuenta que
    publicó el post contenedor (ownerUsername de Fase 1) — no el autor
    del comentario. Es lo que permite separar después, para LATAM, los
    comentarios de @latamairlines (global) de los de
    @latamairlines_colombia (local)."""
    posts = [{
        "url": "https://www.instagram.com/p/ABC123/", "shortCode": "ABC123",
        "type": "Sidecar", "likesCount": 5, "commentsCount": 1,
        "ownerUsername": "latamairlines_colombia",
    }]
    comments = [{
        "id": "1", "text": "Perdieron mi maleta otra vez",
        "ownerUsername": "usuario_quejoso",  # autor del COMENTARIO, distinto del dueño del post
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/ABC123/",
        "commentUrl": "https://www.instagram.com/p/ABC123/c/1",
        "likesCount": 0,
    }]
    fake_client = FakeApifyClient(None, posts=posts, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(LATAM)

    assert len(results) == 1
    assert results[0]["author"] == "usuario_quejoso"
    assert results[0]["source_account"] == "latamairlines_colombia"


def test_comentario_sin_post_correspondiente_deja_source_account_none(monkeypatch):
    """Mismo caso borde que views/reach_source: si el postUrl del
    comentario no está en post_reach, source_account queda None en vez de
    reventar o heredar cualquier otra cosa."""
    comments = [{
        "id": "3", "text": "comentario huérfano",
        "ownerUsername": "usuario3",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/NOEXISTE/",
        "commentUrl": "https://www.instagram.com/p/NOEXISTE/c/3",
        "likesCount": 0,
    }]
    fake_client = FakeApifyClient(None, posts=POSTS, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape(AVIANCA)

    assert len(results) == 1
    assert results[0]["source_account"] is None


# ── Tarea 2 (muestras comparables): el tope de posts subido se respeta ───

def test_fase_1_pide_resultsLimit_igual_a_config_instagram_posts_limit(monkeypatch):
    """La Fase 1 debe pedir exactamente config.INSTAGRAM_POSTS_LIMIT posts
    — no un valor fijo hardcodeado — así que subir el tope en config.py
    (80 -> 200) se refleja sin tocar el scraper."""
    fake_client = FakeApifyClient(None, posts=POSTS, comments=[])
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    apify_instagram.scrape(AVIANCA)

    fase_1 = fake_client.calls[0]
    assert fase_1["resultsType"] == "posts"
    assert fase_1["resultsLimit"] == config.INSTAGRAM_POSTS_LIMIT


# ── scrape_posts: Fase 2 sobre un conjunto de posts elegido a mano ───────
# (muestreo profundo acotado en costo — Tarea 1 de "latam-profundidad")

def test_scrape_posts_sin_urls_no_llama_al_actor(monkeypatch):
    fake_client = FakeApifyClient(None, posts=[], comments=[])
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape_posts(LATAM, [])

    assert results == []
    assert fake_client.calls == []


def test_scrape_posts_pide_fase_1_solo_de_los_post_urls_dados(monkeypatch):
    """scrape_posts NO recorre los perfiles de la marca (eso es scrape()) —
    pide Fase 1 (vía fetch_post_reach) únicamente sobre los post_urls que
    el llamador ya decidió pagar, para no gastar en descubrir posts que
    el presupuesto no alcanza a scrapear en Fase 2."""
    posts = [{
        "url": "https://www.instagram.com/p/COL1/", "shortCode": "COL1",
        "type": "Sidecar", "likesCount": 5, "commentsCount": 1,
        "ownerUsername": "latamairlines_colombia",
    }]
    comments = [{
        "id": "1", "text": "Excelente vuelo, gracias LATAM",
        "ownerUsername": "usuario_contento",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/COL1/",
        "commentUrl": "https://www.instagram.com/p/COL1/c/1",
        "likesCount": 2,
    }]
    fake_client = FakeApifyClient(None, posts=posts, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape_posts(LATAM, ["https://www.instagram.com/p/COL1/"])

    assert len(results) == 1
    assert results[0]["text"] == "Excelente vuelo, gracias LATAM"
    assert results[0]["source_account"] == "latamairlines_colombia"
    # Fase 1 (resultsType='posts') se pidió solo sobre el post_url dado —
    # nunca con directUrls=brand["instagram_profiles"].
    fase_1 = fake_client.calls[0]
    assert fase_1["resultsType"] == "posts"
    assert fase_1["directUrls"] == ["https://www.instagram.com/p/COL1/"]
    # Fase 2 respeta resultsLimit = config.LIMIT_INSTAGRAM, igual que scrape().
    fase_2 = fake_client.calls[1]
    assert fase_2["resultsType"] == "comments"
    assert fase_2["resultsLimit"] == config.LIMIT_INSTAGRAM
    assert fase_2["directUrls"] == ["https://www.instagram.com/p/COL1/"]


def test_scrape_posts_filtra_por_since_igual_que_scrape(monkeypatch):
    posts = [{
        "url": "https://www.instagram.com/p/COL1/", "shortCode": "COL1",
        "ownerUsername": "latamairlines_colombia", "commentsCount": 2,
    }]
    comments = [
        {"id": "1", "text": "comentario viejo", "ownerUsername": "u1",
         "timestamp": "2025-12-01T10:00:00.000Z",
         "postUrl": "https://www.instagram.com/p/COL1/"},
        {"id": "2", "text": "comentario nuevo", "ownerUsername": "u2",
         "timestamp": "2026-06-01T10:00:00.000Z",
         "postUrl": "https://www.instagram.com/p/COL1/"},
    ]
    fake_client = FakeApifyClient(None, posts=posts, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    results = apify_instagram.scrape_posts(
        LATAM, ["https://www.instagram.com/p/COL1/"], since="2026-01-01")

    assert len(results) == 1
    assert results[0]["text"] == "comentario nuevo"


def test_correr_instagram_dos_veces_no_duplica(monkeypatch, tmp_db):
    """scrape() + upsert_mentions() dos veces seguidas con el mismo dataset
    (re-correr la misma ventana, p.ej. tras subir INSTAGRAM_POSTS_LIMIT)
    no debe duplicar filas — el dedup por fingerprint debe ignorar la
    segunda vez por completo."""
    from pipeline.normalizer import normalize

    posts = [{
        "url": "https://www.instagram.com/p/ABC123/", "shortCode": "ABC123",
        "type": "Sidecar", "likesCount": 5, "commentsCount": 1,
        "ownerUsername": "avianca",
    }]
    comments = [{
        "id": "1", "text": "Vuelo cancelado, pésimo servicio",
        "ownerUsername": "usuario1",
        "timestamp": "2026-06-01T10:00:00.000Z",
        "postUrl": "https://www.instagram.com/p/ABC123/",
        "commentUrl": "https://www.instagram.com/p/ABC123/c/1",
        "likesCount": 3,
    }]
    fake_client = FakeApifyClient(None, posts=posts, comments=comments)
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    raw = apify_instagram.scrape(AVIANCA)
    for m in raw:
        m["brand"] = "Avianca"
    mentions = normalize(raw)

    run_id_1 = db.start_run(tmp_db, "weekly", None, brand="Avianca")
    inserted_1, duplicates_1 = db.upsert_mentions(tmp_db, mentions, run_id_1)

    run_id_2 = db.start_run(tmp_db, "weekly", None, brand="Avianca")
    inserted_2, duplicates_2 = db.upsert_mentions(tmp_db, mentions, run_id_2)

    assert inserted_1 == 1
    assert duplicates_1 == 0
    assert inserted_2 == 0
    assert duplicates_2 == 1

    total = tmp_db.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
    assert total == 1
