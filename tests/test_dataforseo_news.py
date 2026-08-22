"""
scrapers/dataforseo_news.py no golpea la API real en tests: requests.post
se mockea con datos GRABADOS de la respuesta real de DataForSEO
(2026-08-21/22, ver docstring del módulo) — incluye la forma real de la
respuesta (bloque top_stories con "items" anidados + elementos
news_search planos), no una versión simplificada inventada.
"""
from unittest.mock import MagicMock, patch

from config import get_brand
from scrapers import dataforseo_news

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")


def _api_response(items):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "tasks": [{"result": [{"items": items}]}]
    }
    return resp


# Grabado real (2026-08-21) para "Avianca": un bloque top_stories con 2
# noticias anidadas (recortado de las 9 reales) + 1 elemento news_search
# suelto, con los campos exactos que devuelve la API — sin "snippet" en
# top_stories, con "snippet" y "time_published" en news_search.
REAL_AVIANCA_ITEMS = [
    {
        "type": "top_stories",
        "title": "Noticias sobre Avianca • Yeferson Cossio",
        "items": [
            {
                "type": "top_stories_element",
                "source": "El Tiempo",
                "domain": "www.eltiempo.com",
                "title": "Yeferson Cossio y Avianca conciliaron por caso 'bomba fétida'",
                "date": "hace 15 horas",
                "timestamp": "2026-08-21 11:14:08 +00:00",
                "url": "https://www.eltiempo.com/cultura/yeferson-cossio-avianca-3579896",
                "image_url": "https://api.dataforseo.com/cdn/i/x:0",
                "badges": None,
            },
            {
                "type": "top_stories_element",
                "source": "Caracol Radio",
                "domain": "caracol.com.co",
                "title": "Yeferson Cossio y Avianca llegan a acuerdo",
                "date": "hace 9 horas",
                "timestamp": "2026-08-21 17:14:08 +00:00",
                "url": "https://caracol.com.co/2026/08/21/yeferson-cossio-avianca/",
                "image_url": "https://api.dataforseo.com/cdn/i/x:1",
                "badges": None,
            },
        ],
    },
    {
        "type": "news_search",
        "domain": "www.asuntoslegales.com.co",
        "title": "Avianca cierra proceso con Yeferson Cossio tras incidente en vuelo",
        "url": "https://www.asuntoslegales.com.co/actualidad/avianca-cierra-4463947",
        "image_url": "https://api.dataforseo.com/cdn/i/x:9",
        "snippet": "El caso se originó luego de que Cossio activara un elemento químico "
                   "prohibido dentro de la cabina de la aeronave.",
        "time_published": "hace 10 horas",
        "timestamp": "2026-08-21 16:14:08 +00:00",
    },
]


@patch("scrapers.dataforseo_news.requests.post")
def test_aplana_top_stories_y_news_search(mock_post):
    mock_post.return_value = _api_response(REAL_AVIANCA_ITEMS)

    results = dataforseo_news.scrape(AVIANCA, since="2026-01-01")

    assert len(results) == 3
    assert all(r["platform"] == "prensa" for r in results)
    dominios = {r["author"] for r in results}
    assert dominios == {"www.eltiempo.com", "caracol.com.co", "www.asuntoslegales.com.co"}


@patch("scrapers.dataforseo_news.requests.post")
def test_combina_titulo_y_snippet_cuando_hay_snippet(mock_post):
    mock_post.return_value = _api_response(REAL_AVIANCA_ITEMS)

    results = dataforseo_news.scrape(AVIANCA, since=None)

    con_snippet = next(r for r in results if r["author"] == "www.asuntoslegales.com.co")
    assert con_snippet["text"].startswith("Avianca cierra proceso")
    assert "químico prohibido" in con_snippet["text"]

    sin_snippet = next(r for r in results if r["author"] == "www.eltiempo.com")
    assert sin_snippet["text"] == "Yeferson Cossio y Avianca conciliaron por caso 'bomba fétida'"


@patch("scrapers.dataforseo_news.requests.post")
def test_parsea_timestamp_a_iso(mock_post):
    mock_post.return_value = _api_response(REAL_AVIANCA_ITEMS)

    results = dataforseo_news.scrape(AVIANCA, since=None)

    fila = next(r for r in results if r["author"] == "www.eltiempo.com")
    assert fila["published_at"].startswith("2026-08-21T11:14:08")
    # date_confidence lo deriva normalize() a partir de published_at
    # (pipeline/normalizer.py) — este scraper no lo pone.
    assert "date_confidence" not in fila


@patch("scrapers.dataforseo_news.requests.post")
def test_since_filtra_del_lado_del_cliente(mock_post):
    mock_post.return_value = _api_response(REAL_AVIANCA_ITEMS)

    # Todas las notas grabadas son del 2026-08-21 — un since del mismo
    # día no debe descartar nada, uno posterior debe descartar todo.
    results_mismo_dia = dataforseo_news.scrape(AVIANCA, since="2026-08-21")
    results_futuro = dataforseo_news.scrape(AVIANCA, since="2026-09-01")

    assert len(results_mismo_dia) == 3
    assert results_futuro == []


@patch("scrapers.dataforseo_news.requests.post")
def test_dedup_por_url_entre_top_stories_y_news_search(mock_post):
    """Verificado con datos reales: top_stories y news_search a veces
    repiten el mismo artículo (1 de 20 en la corrida real) — no debe
    duplicarse en el resultado."""
    items = [
        {
            "type": "top_stories",
            "items": [{
                "domain": "www.eltiempo.com", "title": "Nota X",
                "timestamp": "2026-08-21 11:14:08 +00:00",
                "url": "https://www.eltiempo.com/nota-x",
            }],
        },
        {
            "type": "news_search",
            "domain": "www.eltiempo.com", "title": "Nota X",
            "url": "https://www.eltiempo.com/nota-x",
            "snippet": "misma nota, repetida",
            "timestamp": "2026-08-21 11:14:08 +00:00",
        },
    ]
    mock_post.return_value = _api_response(items)

    results = dataforseo_news.scrape(AVIANCA, since=None)

    assert len(results) == 1


@patch("scrapers.dataforseo_news.requests.post")
def test_tipo_desconocido_sin_items_ni_domain_se_ignora(mock_post):
    items = [{"type": "algo_nuevo_que_no_existe_hoy", "rectangle": None}]
    mock_post.return_value = _api_response(items)

    results = dataforseo_news.scrape(AVIANCA, since=None)

    assert results == []


@patch("scrapers.dataforseo_news.requests.post")
def test_respuesta_sin_items_no_lanza(mock_post):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"tasks": [{"result": []}]}
    mock_post.return_value = resp

    assert dataforseo_news.scrape(AVIANCA, since=None) == []


@patch("scrapers.dataforseo_news.requests.post")
def test_usa_keyword_y_location_de_la_marca_pasada(mock_post):
    """El payload debe reflejar la marca del parámetro, no una constante
    fija — mismo argumento que ya vale para is_relevant/classifier."""
    mock_post.return_value = _api_response([])

    dataforseo_news.scrape(LATAM, since=None)

    payload = mock_post.call_args.kwargs["json"]
    assert payload[0]["keyword"] == "LATAM"
