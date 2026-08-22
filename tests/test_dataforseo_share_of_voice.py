"""
scrapers/dataforseo_share_of_voice.py no golpea la API real en tests:
requests.post se mockea con datos GRABADOS de la respuesta real de
DataForSEO (2026-08-22, ver docstring del módulo) para
keywords_data/google_ads/search_volume/live y
ai_optimization/ai_keyword_data/keywords_search_volume/live.
"""
from unittest.mock import MagicMock, patch

from config import get_brand
from scrapers import dataforseo_share_of_voice as m

AVIANCA = get_brand("Avianca")


def _resp(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


# Grabado real (2026-08-22), recortado a 4 de las 20 keywords reales
# (5 de problema + 5 comerciales x 2 marcas) — cost real del request
# completo de 20 keywords: $0,09.
REAL_GOOGLE_ADS_RESPONSE = {
    "tasks": [{
        "status_code": 20000, "cost": 0.09,
        "result": [
            {"keyword": "avianca demanda", "search_volume": 10,
             "competition": "LOW", "competition_index": 0},
            {"keyword": "avianca reclamo", "search_volume": 390,
             "competition": "LOW", "competition_index": 12, "cpc": 2.41},
            {"keyword": "avianca queja", "search_volume": 480,
             "competition": "LOW", "competition_index": 4},
            {"keyword": "avianca vuelos", "search_volume": 12000,
             "competition": "MEDIUM", "competition_index": 40},
        ],
    }]
}

# Grabado real (2026-08-22) para 3 keywords — cost=$0,0103 ($0,0034-0,0035
# por keyword aprox.).
REAL_AI_KEYWORD_RESPONSE = {
    "tasks": [{
        "status_code": 20000, "cost": 0.0103,
        "result": [{
            "location_code": 2170, "language_code": "es", "items_count": 3,
            "items": [
                {"keyword": "avianca", "ai_search_volume": 3961},
                {"keyword": "avianca reclamo", "ai_search_volume": 3},
                {"keyword": "avianca vuelos", "ai_search_volume": 906},
            ],
        }],
    }]
}


def _fake_post(url, headers=None, json=None, timeout=None):
    if "google_ads" in url:
        return _resp(REAL_GOOGLE_ADS_RESPONSE)
    if "keywords_search_volume" in url:
        return _resp(REAL_AI_KEYWORD_RESPONSE)
    raise AssertionError(f"URL inesperada: {url}")


@patch("scrapers.dataforseo_share_of_voice.requests.post")
def test_scrape_llama_a_los_dos_motores(mock_post):
    mock_post.side_effect = _fake_post

    rows = m.scrape(AVIANCA)

    assert mock_post.call_count == 2
    engines = {r["engine"] for r in rows}
    assert engines == {"google_ads", "ai_search"}


@patch("scrapers.dataforseo_share_of_voice.requests.post")
def test_intencion_problema_vs_comercial_se_preserva(mock_post):
    mock_post.side_effect = _fake_post

    rows = m.scrape(AVIANCA)

    por_keyword = {(r["keyword"], r["engine"]): r for r in rows}
    assert por_keyword[("avianca reclamo", "google_ads")]["intent"] == "problema"
    assert por_keyword[("avianca vuelos", "google_ads")]["intent"] == "comercial"
    assert por_keyword[("avianca reclamo", "google_ads")]["search_volume"] == 390
    assert por_keyword[("avianca vuelos", "google_ads")]["search_volume"] == 12000


@patch("scrapers.dataforseo_share_of_voice.requests.post")
def test_ai_search_usa_ai_search_volume_no_search_volume(mock_post):
    """El endpoint de ai_keyword_data devuelve `ai_search_volume`, no
    `search_volume` (nombre de campo distinto al de google_ads) — el
    scraper debe leer el campo correcto para ese motor."""
    mock_post.side_effect = _fake_post

    rows = m.scrape(AVIANCA)

    fila = next(r for r in rows if r["engine"] == "ai_search" and r["keyword"] == "avianca vuelos")
    assert fila["search_volume"] == 906


@patch("scrapers.dataforseo_share_of_voice.requests.post")
def test_todas_las_filas_llevan_marca_y_fecha_de_captura(mock_post):
    mock_post.side_effect = _fake_post

    rows = m.scrape(AVIANCA)

    assert all(r["brand"] == "Avianca" for r in rows)
    assert all(r["captured_at"] for r in rows)


@patch("scrapers.dataforseo_share_of_voice.requests.post")
def test_un_motor_fallido_no_descarta_el_otro(mock_post):
    def fake_post_con_falla(url, headers=None, json=None, timeout=None):
        if "google_ads" in url:
            return _resp({"tasks": [{"status_code": 40400, "status_message": "Not Found."}]})
        return _resp(REAL_AI_KEYWORD_RESPONSE)
    mock_post.side_effect = fake_post_con_falla

    rows = m.scrape(AVIANCA)

    assert all(r["engine"] == "ai_search" for r in rows)
    # REAL_AI_KEYWORD_RESPONSE trae 3 items, pero "avianca" a secas no es
    # ninguna de las keywords generadas (todas son "avianca + término") —
    # solo "avianca reclamo" y "avianca vuelos" hacen match.
    assert len(rows) == 2
