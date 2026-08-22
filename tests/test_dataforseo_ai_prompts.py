"""
scrapers/dataforseo_ai_prompts.py no golpea la API real en tests:
requests.post se mockea con datos GRABADOS de la respuesta real de
DataForSEO (2026-08-22, ver docstring del módulo) para
ai_optimization/chat_gpt/llm_responses/live. classify_texts se mockea
también — el sentimiento real ya se prueba en tests/test_classifier.py,
acá solo importa que este módulo lo llame bien y guarde lo que devuelve.
"""
from unittest.mock import MagicMock, patch

from config import get_brand
from scrapers import dataforseo_ai_prompts as m

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")

CLASIFICADO = {
    "sentiment_positive": 0.7, "sentiment_negative": 0.1, "sentiment_neutral": 0.2,
    "emotion": "happiness", "is_complaint": False, "complaint_driver": None,
}


def _resp(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


# Grabado real (2026-08-22) para "¿Es confiable Avianca como aerolínea?"
# (gpt-4o-mini, max_output_tokens=400) — cost=$0,000763. Texto recortado
# a las primeras líneas de la respuesta real completa.
REAL_CHATGPT_RESPONSE = {
    "tasks": [{
        "status_code": 20000, "status_message": "Ok.", "cost": 0.000763,
        "result": [{
            "model_name": "gpt-4o-mini-2024-07-18",
            "input_tokens": 29, "output_tokens": 264, "reasoning_tokens": 0,
            "web_search": False, "money_spent": 0.00016275,
            "datetime": "2026-08-22 11:57:28 +00:00",
            "items": [{
                "type": "message",
                "sections": [{
                    "type": "text",
                    "text": (
                        "Avianca es una de las aerolíneas más antiguas y reconocidas "
                        "de América Latina, fundada en 1919. En general, se considera "
                        "confiable, con una amplia trayectoria en el sector de la "
                        "aviación."
                    ),
                    "annotations": None,
                }],
            }],
            "fan_out_queries": None,
        }],
    }]
}

RESPUESTA_COMPARATIVA = {
    "tasks": [{
        "status_code": 20000,
        "result": [{
            "model_name": "gpt-4o-mini-2024-07-18",
            "input_tokens": 20, "output_tokens": 90, "money_spent": 0.0006,
            "items": [{"sections": [{
                "type": "text",
                "text": "Avianca suele ser mejor valorada que LATAM en puntualidad, "
                        "aunque LATAM tiene más rutas internacionales.",
            }]}],
        }],
    }]
}


@patch("scrapers.dataforseo_ai_prompts.classify_texts")
@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_scrape_corre_todos_los_prompts_del_perfil(mock_post, mock_classify):
    mock_post.return_value = _resp(REAL_CHATGPT_RESPONSE)
    mock_classify.return_value = [CLASIFICADO]

    results = m.scrape(AVIANCA)

    from config import get_ai_prompts
    assert len(results) == len(get_ai_prompts("Avianca"))
    assert mock_post.call_count == len(get_ai_prompts("Avianca"))


@patch("scrapers.dataforseo_ai_prompts.classify_texts")
@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_guarda_prompt_modelo_y_respuesta_completa(mock_post, mock_classify):
    mock_post.return_value = _resp(REAL_CHATGPT_RESPONSE)
    mock_classify.return_value = [CLASIFICADO]

    results = m.scrape(AVIANCA)

    item = results[0]
    assert item["response"]["model"] == "gpt-4o-mini-2024-07-18"
    assert item["response"]["platform"] == "chat_gpt"
    assert "Avianca" in item["response"]["response_text"]
    assert item["response"]["prompt"]
    assert item["response"]["money_spent"] == 0.00016275


@patch("scrapers.dataforseo_ai_prompts.classify_texts")
@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_categoria_evalua_ambas_marcas_desde_una_sola_respuesta(mock_post, mock_classify):
    """Un prompt de categoría (sin marca propia) no debe pagar dos veces
    la misma pregunta: la comparación Avianca/LATAM sale de UNA respuesta."""
    mock_post.return_value = _resp(RESPUESTA_COMPARATIVA)
    mock_classify.return_value = [CLASIFICADO]

    results = m.scrape(AVIANCA)
    categoria = next(r for r in results if r["response"]["prompt_scope"] == "category")

    marcas = {mn["brand"] for mn in categoria["mentions"]}
    assert marcas == {"Avianca", "LATAM"}


@patch("scrapers.dataforseo_ai_prompts.classify_texts")
@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_posicion_refleja_orden_de_aparicion(mock_post, mock_classify):
    mock_post.return_value = _resp(RESPUESTA_COMPARATIVA)
    mock_classify.return_value = [CLASIFICADO]

    results = m.scrape(AVIANCA)
    categoria = next(r for r in results if r["response"]["prompt_scope"] == "category")
    por_marca = {mn["brand"]: mn for mn in categoria["mentions"]}

    # "Avianca suele ser mejor valorada que LATAM..." — Avianca aparece
    # primero en el texto.
    assert por_marca["Avianca"]["position"] == 1
    assert por_marca["LATAM"]["position"] == 2
    assert por_marca["Avianca"]["appears"] is True
    assert por_marca["LATAM"]["appears"] is True


@patch("scrapers.dataforseo_ai_prompts.classify_texts")
@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_marca_ausente_no_se_clasifica(mock_post, mock_classify):
    """Si el competidor no aparece en el texto, no hay sentimiento que
    sacarle — classify_texts no debe llamarse para esa marca, y su fila
    debe quedar sin clasificar (no un neutral inventado)."""
    solo_avianca = {
        "tasks": [{"status_code": 20000, "result": [{
            "model_name": "gpt-4o-mini",
            "items": [{"sections": [{"type": "text", "text": "Avianca es una buena opción."}]}],
        }]}]
    }
    mock_post.return_value = _resp(solo_avianca)
    mock_classify.return_value = [CLASIFICADO]

    results = m.scrape(AVIANCA)
    categoria = next(r for r in results if r["response"]["prompt_scope"] == "category")
    por_marca = {mn["brand"]: mn for mn in categoria["mentions"]}

    assert por_marca["LATAM"]["appears"] is False
    assert por_marca["LATAM"]["position"] is None
    assert por_marca["LATAM"]["classification_status"] == "unclassified"
    assert por_marca["LATAM"]["sentiment_positive"] is None
    # Cada uno de los 6 prompts devolvió el mismo texto mockeado (solo
    # menciona a Avianca) — classify_texts se llamó una vez POR PROMPT
    # (para Avianca), nunca para LATAM, que no aparece en ningún texto.
    assert mock_classify.call_count == len(results)
    marcas_clasificadas = {call.args[1]["name"] for call in mock_classify.call_args_list}
    assert marcas_clasificadas == {"Avianca"}


@patch("scrapers.dataforseo_ai_prompts.classify_texts")
@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_prompts_de_marca_traen_subject_brand(mock_post, mock_classify):
    mock_post.return_value = _resp(REAL_CHATGPT_RESPONSE)
    mock_classify.return_value = [CLASIFICADO]

    results = m.scrape(AVIANCA)
    de_marca = [r for r in results if r["response"]["prompt_scope"] == "brand"]

    assert de_marca  # el set de Avianca sí trae plantillas de marca
    assert all(r["response"]["subject_brand"] == "Avianca" for r in de_marca)
    categoria = [r for r in results if r["response"]["prompt_scope"] == "category"]
    assert all(r["response"]["subject_brand"] is None for r in categoria)


@patch("scrapers.dataforseo_ai_prompts.requests.post")
def test_prompt_fallido_no_tumba_el_resto(mock_post):
    """El primer prompt falla (status_code de error); el resto debe
    seguir procesándose."""
    llamadas = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return _resp({"tasks": [{"status_code": 40400, "status_message": "Not Found."}]})
        return _resp(REAL_CHATGPT_RESPONSE)

    mock_post.side_effect = fake_post
    with patch("scrapers.dataforseo_ai_prompts.classify_texts", return_value=[CLASIFICADO]):
        results = m.scrape(AVIANCA)

    from config import get_ai_prompts
    assert len(results) == len(get_ai_prompts("Avianca")) - 1
