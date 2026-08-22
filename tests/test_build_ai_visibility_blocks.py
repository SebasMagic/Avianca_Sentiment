"""
Tarea 3: bloques nuevos del dashboard (visibilidad en IA + share of
voice) en dashboard/template.html. Mismo patrón que el resto de
tests/test_build.py — pruebas sobre el HTML ya renderizado por
build.render(), sin runtime de JS (el comportamiento en vivo se verificó
aparte con jsdom + Playwright, ver .superpowers/visibilidad-ia.md).
"""
from dashboard import build
from tests.test_build import PAYLOAD


def test_bloques_10_y_11_existen_en_el_html():
    html = build.render(PAYLOAD)
    for block_id in ("b10", "b10a", "b10b", "b10c", "b10d", "b10e", "b11"):
        assert f'id="{block_id}"' in html


def test_ids_de_render_target_existen():
    html = build.render(PAYLOAD)
    for el_id in ("aivCompare", "aivSources", "aivCategory",
                  "aivBrandPrompts", "aivSearchExamples", "sovCard"):
        assert f'id="{el_id}"' in html


def test_funciones_de_render_nuevas_estan_declaradas_y_se_invocan():
    html = build.render(PAYLOAD)
    # El dispatcher final es el ÚLTIMO "].forEach(fn => fn());" del
    # documento (el vendor de Chart.js, inyectado por __CHARTJS__, trae
    # sus propios "].forEach" internos — buscar desde el final evita
    # matchear esos en vez del dispatcher real).
    dispatcher = html.rsplit("].forEach(fn => fn());", 1)[0].rsplit("[", 1)[-1]
    for fn in (
        "renderAIVisibilityCompare", "renderAIVisibilitySources",
        "renderAIVisibilityCategory", "renderAIVisibilityBrandPrompts",
        "renderAIVisibilitySearchExamples", "renderShareOfVoice",
    ):
        assert f"function {fn}(" in html
        # Cada una debe estar en el array del dispatcher final, no solo
        # declarada — una función que nunca se llama es un bloque muerto.
        assert fn in dispatcher


def test_payload_sin_ai_visibility_no_rompe_el_render():
    """PAYLOAD (fixture mínima de test_build.py) no trae "ai_visibility"
    ni "share_of_voice" — el render no debe fallar, y el HTML resultante
    debe seguir siendo JSON válido en el marcador de datos."""
    html = build.render(PAYLOAD)
    assert "__DASHBOARD_DATA__" not in html
    assert '"ai_visibility"' not in html  # la fixture no la trae


def test_payload_con_datos_de_ai_visibility_se_incrusta_en_el_json():
    payload = {
        **PAYLOAD,
        "ai_visibility": {
            "brand": "Avianca",
            "own": {"brand": "Avianca", "mentions": 1091, "ai_search_volume": 839350,
                     "domain": "avianca.com", "captured_at": "2026-08-22T00:00:00+00:00",
                     "source_endpoint": "target_metrics",
                     "sources": [{"domain": "www.latamairlines.com", "mentions": 246,
                                   "ai_search_volume": 161710, "is_own_domain": False,
                                   "is_competitor_domain": True}]},
            "competitors": [{"brand": "LATAM", "mentions": 1079, "ai_search_volume": 1037930}],
            "missing_competitors": [],
            "category_prompts": [], "brand_prompts": [], "search_examples": [],
            "has_metrics": True, "has_prompts": False, "has_search_examples": False,
            "captured_at": "2026-08-22T00:00:00+00:00",
        },
        "share_of_voice": {
            "brand": "Avianca", "by_engine": {}, "has_data": False, "captured_at": None,
        },
    }
    html = build.render(payload)
    assert "www.latamairlines.com" in html
    assert '"is_competitor_domain": true' in html.lower() or '"is_competitor_domain":true' in html.lower()


def test_marcadores_de_marca_sin_sustituir_no_quedan_en_el_html():
    """Regresión rápida: el bloque nuevo no debe introducir texto que
    parezca un marcador __BRAND_...__ sin reemplazar."""
    html = build.render(PAYLOAD)
    assert "__BRAND_" not in html
