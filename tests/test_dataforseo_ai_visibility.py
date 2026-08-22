"""
scrapers/dataforseo_ai_visibility.py no golpea la API real en tests:
requests.post se mockea con datos GRABADOS de la respuesta real de
DataForSEO (2026-08-22, ver docstring del módulo) para target_metrics,
multi_target_metrics y search_mentions.
"""
from unittest.mock import MagicMock, patch

from config import get_brand
from scrapers import dataforseo_ai_visibility as m

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")


def _resp(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


# Grabado real (2026-08-22) para avianca.com — recortado a las primeras
# entradas de sources_domain (la real trae 10), con los campos exactos que
# devuelve la API: cost=$0,101 (tarifa base $0,1 + $0,001 por la única
# fila agregada). El hallazgo real: www.latamairlines.com aparece entre
# las fuentes que citan a Avianca.
REAL_TARGET_METRICS_AVIANCA = {
    "tasks": [{
        "status_code": 20000, "status_message": "Ok.", "cost": 0.101,
        "result": [{
            "total_count": 0, "items_count": 0,
            "aggregated_metrics": {
                "platform": [{"key": "google", "mentions": 1091, "ai_search_volume": 839350}],
                "sources_domain": [
                    {"key": "www.avianca.com", "mentions": 1091, "ai_search_volume": 839350},
                    {"key": "www.kayak.com.co", "mentions": 383, "ai_search_volume": 196530},
                    {"key": "www.youtube.com", "mentions": 257, "ai_search_volume": 189590},
                    {"key": "www.latamairlines.com", "mentions": 246, "ai_search_volume": 161710},
                    {"key": "ayuda.avianca.com", "mentions": 219, "ai_search_volume": 208300},
                ],
                "search_results_domain": [], "brand_entities_title": [],
                "brand_entities_category": [],
                "total": {"mentions": 1091, "ai_search_volume": 839350},
            },
            "items": [],
        }],
    }]
}

# Grabado real (2026-08-22) para latamairlines.com — mismo endpoint, otro
# dominio. avianca.com aparece entre sus fuentes: la citación cruzada va
# en las dos direcciones.
REAL_TARGET_METRICS_LATAM = {
    "tasks": [{
        "status_code": 20000, "status_message": "Ok.", "cost": 0.101,
        "result": [{
            "total_count": 0, "items_count": 0,
            "aggregated_metrics": {
                "platform": [{"key": "google", "mentions": 1079, "ai_search_volume": 1037930}],
                "sources_domain": [
                    {"key": "www.latamairlines.com", "mentions": 1079, "ai_search_volume": 1037930},
                    {"key": "www.youtube.com", "mentions": 357, "ai_search_volume": 479430},
                    {"key": "www.instagram.com", "mentions": 308, "ai_search_volume": 269090},
                    {"key": "www.kayak.com.co", "mentions": 293, "ai_search_volume": 186480},
                    {"key": "www.avianca.com", "mentions": 246, "ai_search_volume": 161710},
                ],
                "search_results_domain": [], "brand_entities_title": [],
                "brand_entities_category": [],
                "total": {"mentions": 1079, "ai_search_volume": 1037930},
            },
            "items": [],
        }],
    }]
}

# Grabado real (2026-08-22), recortado a 1 de los 5 items reales
# (limit=5): pregunta+respuesta real que Google AI Overview ya contesta
# sobre Avianca, con su fuente citada.
REAL_SEARCH_MENTIONS_AVIANCA = {
    "tasks": [{
        "status_code": 20000, "cost": 0.105,
        "result": [{
            "total_count": 1091, "items_count": 1,
            "items": [{
                "platform": "google", "model_name": "google_ai_overview",
                "location_code": 2170, "language_code": "es",
                "question": "avianca airlines check-in",
                "answer": (
                    "El check-in de Avianca se realiza entre 48 horas (para vuelos "
                    "nacionales e internacionales) y 24 horas (para vuelos desde/hacia "
                    "EE. UU. y Canadá) antes de la salida."
                ),
                "sources": [{
                    "snippet": "Realiza tu check-in online...",
                    "source_name": "Avianca", "rank": 1,
                    "title": "Check-in online | Avianca Oficial",
                    "domain": "www.avianca.com",
                    "url": "https://www.avianca.com/es/mi-reserva/servicios/check-in-online",
                }],
                "ai_search_volume": 110000,
            }],
        }],
    }]
}

# Grabado real (2026-08-22) de multi_target_metrics para las dos marcas en
# un solo request (cost=$0,102): el mismo agregado que target_metrics,
# pero por marca en items[], identificado por la "key" que se manda en el
# request (no por "domain").
REAL_MULTI_TARGET_METRICS = {
    "tasks": [{
        "status_code": 20000, "status_message": "Ok.", "cost": 0.102,
        "result": [{
            "total_count": 2, "items_count": 2,
            "aggregated_metrics": {"total": {"mentions": 1924, "ai_search_volume": 1715570}},
            "items": [
                {
                    "key": "Avianca",
                    "platform": [{"key": "google", "mentions": 1091, "ai_search_volume": 839350}],
                    "sources_domain": [
                        {"key": "www.avianca.com", "mentions": 1091, "ai_search_volume": 839350},
                        {"key": "www.latamairlines.com", "mentions": 246, "ai_search_volume": 161710},
                    ],
                    "total": {"mentions": 1091, "ai_search_volume": 839350},
                },
                {
                    "key": "LATAM",
                    "platform": [{"key": "google", "mentions": 1079, "ai_search_volume": 1037930}],
                    "sources_domain": [
                        {"key": "www.latamairlines.com", "mentions": 1079, "ai_search_volume": 1037930},
                        {"key": "www.avianca.com", "mentions": 246, "ai_search_volume": 161710},
                    ],
                    "total": {"mentions": 1079, "ai_search_volume": 1037930},
                },
            ],
        }],
    }]
}


def _fake_post_factory(target_resp, search_resp=None):
    def fake_post(url, headers=None, json=None, timeout=None):
        if "target_metrics" in url:
            return _resp(target_resp)
        if "search_mentions" in url:
            return _resp(search_resp or {"tasks": [{"status_code": 20000, "result": [{"items": []}]}]})
        if "multi_target_metrics" in url:
            return _resp(target_resp)
        raise AssertionError(f"URL inesperada: {url}")
    return fake_post


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_extrae_metricas_agregadas(mock_post):
    mock_post.side_effect = _fake_post_factory(
        REAL_TARGET_METRICS_AVIANCA, REAL_SEARCH_MENTIONS_AVIANCA)

    out = m.scrape(AVIANCA)

    assert len(out["brand_metrics"]) == 1
    fila = out["brand_metrics"][0]
    assert fila["brand"] == "Avianca"
    assert fila["domain"] == "avianca.com"
    assert fila["mentions"] == 1091
    assert fila["ai_search_volume"] == 839350
    assert fila["source_endpoint"] == "target_metrics"


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_marca_dominio_del_competidor_entre_las_fuentes(mock_post):
    """El hallazgo real: latamairlines.com aparece citado al hablar de
    Avianca — is_competitor_domain debe quedar en True para esa fila."""
    mock_post.side_effect = _fake_post_factory(
        REAL_TARGET_METRICS_AVIANCA, REAL_SEARCH_MENTIONS_AVIANCA)

    out = m.scrape(AVIANCA)

    fuentes = {f["cited_domain"]: f for f in out["brand_sources"]}
    assert fuentes["www.latamairlines.com"]["is_competitor_domain"] is True
    assert fuentes["www.latamairlines.com"]["is_own_domain"] is False
    assert fuentes["www.avianca.com"]["is_own_domain"] is True
    assert fuentes["www.avianca.com"]["is_competitor_domain"] is False
    # Un dominio de terceros (no propio, no de ningún competidor conocido)
    # no debe quedar marcado como ninguno de los dos.
    assert fuentes["www.kayak.com.co"]["is_own_domain"] is False
    assert fuentes["www.kayak.com.co"]["is_competitor_domain"] is False


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_latam_marca_avianca_como_competidor(mock_post):
    """Simétrico: procesando LATAM, avianca.com debe quedar marcado como
    dominio de un competidor — la citación cruzada va en las dos direcciones."""
    mock_post.side_effect = _fake_post_factory(
        REAL_TARGET_METRICS_LATAM, {"tasks": [{"status_code": 20000, "result": [{"items": []}]}]})

    out = m.scrape(LATAM)

    fuentes = {f["cited_domain"]: f for f in out["brand_sources"]}
    assert fuentes["www.avianca.com"]["is_competitor_domain"] is True


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_extrae_ejemplo_real_de_qa(mock_post):
    mock_post.side_effect = _fake_post_factory(
        REAL_TARGET_METRICS_AVIANCA, REAL_SEARCH_MENTIONS_AVIANCA)

    out = m.scrape(AVIANCA)

    assert len(out["search_examples"]) == 1
    ejemplo = out["search_examples"][0]
    assert ejemplo["question"] == "avianca airlines check-in"
    assert "check-in" in ejemplo["answer"].lower()
    assert ejemplo["top_source_domain"] == "www.avianca.com"
    assert ejemplo["ai_search_volume"] == 110000


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_sin_review_domain_no_llama_a_la_api(mock_post):
    brand_sin_dominio = {**AVIANCA, "review_domain": None}
    out = m.scrape(brand_sin_dominio)
    mock_post.assert_not_called()
    assert out == {"brand_metrics": [], "brand_sources": [], "search_examples": []}


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_endpoint_fallido_no_tumba_los_otros(mock_post):
    """target_metrics falla (status_code de error) pero search_mentions sí
    responde — el resultado debe traer los ejemplos igual, sin reventar."""
    def fake_post(url, headers=None, json=None, timeout=None):
        if "target_metrics" in url:
            return _resp({"tasks": [{"status_code": 40400, "status_message": "Not Found."}]})
        return _resp(REAL_SEARCH_MENTIONS_AVIANCA)
    mock_post.side_effect = fake_post

    out = m.scrape(AVIANCA)

    assert out["brand_metrics"] == []
    assert out["brand_sources"] == []
    assert len(out["search_examples"]) == 1


# ── scrape_comparison (multi_target_metrics) ─────────────────────────────

@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_comparison_devuelve_ambas_marcas_de_un_solo_request(mock_post):
    mock_post.return_value = _resp(REAL_MULTI_TARGET_METRICS)

    out = m.scrape_comparison(["Avianca", "LATAM"])

    assert mock_post.call_count == 1  # un solo request para las dos marcas
    marcas = {f["brand"]: f for f in out["brand_metrics"]}
    assert marcas["Avianca"]["mentions"] == 1091
    assert marcas["LATAM"]["mentions"] == 1079
    assert all(f["source_endpoint"] == "multi_target_metrics" for f in out["brand_metrics"])


@patch("scrapers.dataforseo_ai_visibility.requests.post")
def test_scrape_comparison_envia_key_por_marca(mock_post):
    """Formato verificado contra la API real: sin "key" en cada entrada de
    `targets`, la API responde 40501 "Field 'key' is required" — el
    request tiene que mandarlo siempre."""
    mock_post.return_value = _resp(REAL_MULTI_TARGET_METRICS)

    m.scrape_comparison(["Avianca", "LATAM"])

    _, kwargs = mock_post.call_args
    targets = kwargs["json"][0]["targets"]
    assert all("key" in t and t["key"] for t in targets)
