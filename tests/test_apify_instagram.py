"""
scrapers/apify_instagram.py no golpea la API real en tests: se
monkeypatchea ApifyClient por un doble de prueba que sirve datasets fijos.
"""
from config import get_brand
from scrapers import apify_instagram

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
    """_post_reach_map extrae exactamente views/likes/comments de un item
    de post — fixture con los mismos nombres de clave verificados contra
    la API real (2026-08-20)."""
    posts = [
        {"url": "https://www.instagram.com/p/V1/", "type": "Video",
         "videoPlayCount": 100, "likesCount": 10, "commentsCount": 2},
        {"url": "https://www.instagram.com/p/S1/", "type": "Sidecar",
         "likesCount": 20, "commentsCount": 4},
        {"error": "no encontrado"},  # ítem de error del actor: se ignora
    ]
    reach = apify_instagram._post_reach_map(posts)

    assert reach["https://www.instagram.com/p/V1/"] == {"views": 100, "likes": 10, "comments": 2}
    assert reach["https://www.instagram.com/p/S1/"] == {"views": None, "likes": 20, "comments": 4}
    assert len(reach) == 2


def test_fetch_post_reach_llama_fase_1_con_directUrls_de_posts(monkeypatch):
    """fetch_post_reach (usado por el backfill retroactivo, Tarea 2) pide
    resultsType='posts' con directUrls=post_urls específicos — no perfiles,
    no re-pide comentarios."""
    posts = [{"url": "https://www.instagram.com/p/V1/", "type": "Video",
              "videoPlayCount": 999, "likesCount": 5, "commentsCount": 1}]
    fake_client = FakeApifyClient(None, posts=posts, comments=[])
    monkeypatch.setattr(apify_instagram, "ApifyClient", lambda token: fake_client)

    reach = apify_instagram.fetch_post_reach(["https://www.instagram.com/p/V1/"])

    assert reach == {"https://www.instagram.com/p/V1/": {"views": 999, "likes": 5, "comments": 1}}
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
