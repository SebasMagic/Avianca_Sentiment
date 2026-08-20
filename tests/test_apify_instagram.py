"""
scrapers/apify_instagram.py no golpea la API real en tests: se
monkeypatchea ApifyClient por un doble de prueba que sirve datasets fijos.
"""
from scrapers import apify_instagram


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

    results = apify_instagram.scrape()

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

    results = apify_instagram.scrape()

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

    results = apify_instagram.scrape()

    assert len(results) == 1
    assert results[0]["source_url"] == "https://www.instagram.com/p/ABC123/"
