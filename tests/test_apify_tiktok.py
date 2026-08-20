"""
scrapers/apify_tiktok.py no golpea la API real en tests: se monkeypatchea
ApifyClient por un doble de prueba que sirve un dataset fijo.
"""
from scrapers import apify_tiktok


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
        return {"defaultDatasetId": "videos"}


class FakeApifyClient:
    """Doble de ApifyClient: un dataset fijo de videos."""

    def __init__(self, token, *, items):
        self._items = items
        self.calls = []

    def actor(self, actor_id):
        return _FakeActorHandle(self)

    def dataset(self, dataset_id):
        return _FakeDataset(self._items)


ITEMS = [
    {
        "id": "1",
        "text": "video viejo sobre Avianca",
        "createTimeISO": "2023-03-23T00:00:00.000Z",
        "authorMeta": {"name": "user_viejo"},
        "webVideoUrl": "https://tiktok.com/@user_viejo/video/1",
    },
    {
        "id": "2",
        "text": "video nuevo sobre Avianca",
        "createTimeISO": "2026-05-01T00:00:00.000Z",
        "authorMeta": {"name": "user_nuevo"},
        "webVideoUrl": "https://tiktok.com/@user_nuevo/video/2",
    },
]


def test_filtra_items_anteriores_a_since_aunque_el_actor_los_devuelva(monkeypatch):
    """
    Defecto verificado con datos reales: clockworks/tiktok-scraper ignora
    oldestPostDate y devuelve videos fuera del rango pedido (un backfill con
    --since 2026-04-19 trajo igual 24 videos de 2023-2025). El actor del
    fake simula exactamente eso — devuelve un item viejo y uno nuevo sin
    importar el "since" pedido — y el filtro debe descartar el viejo del
    lado del cliente.
    """
    fake_client = FakeApifyClient(None, items=ITEMS)
    monkeypatch.setattr(apify_tiktok, "ApifyClient", lambda token: fake_client)

    results = apify_tiktok.scrape(since="2026-04-19")

    assert len(results) == 1
    assert results[0]["text"] == "video nuevo sobre Avianca"


def test_actor_igual_recibe_oldestPostDate_como_defensa_en_profundidad(monkeypatch):
    """El parámetro del actor se conserva — no se reemplaza por el filtro
    del cliente, se suma a él."""
    fake_client = FakeApifyClient(None, items=ITEMS)
    monkeypatch.setattr(apify_tiktok, "ApifyClient", lambda token: fake_client)

    apify_tiktok.scrape(since="2026-04-19")

    assert fake_client.calls[0]["oldestPostDate"] == "2026-04-19"


def test_sin_since_no_filtra_nada(monkeypatch):
    fake_client = FakeApifyClient(None, items=ITEMS)
    monkeypatch.setattr(apify_tiktok, "ApifyClient", lambda token: fake_client)

    results = apify_tiktok.scrape()

    assert len(results) == 2
