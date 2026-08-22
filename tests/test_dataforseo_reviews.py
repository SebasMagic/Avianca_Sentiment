"""
scrapers/dataforseo_reviews.py no golpea la API real en tests:
requests.post/requests.get se mockean con datos GRABADOS de la API real
de DataForSEO (2026-08-21/22, ver docstring del módulo) — incluye la
secuencia asíncrona real (task_post -> task_get "En cola" -> task_get
"Ok") y los campos exactos de un ítem de reseña de Trustpilot.
time.sleep se mockea para que el backoff no ralentice la suite.
"""
from unittest.mock import MagicMock, patch

from config import get_brand
from scrapers import dataforseo_reviews

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")


def _post_response(task_id="08220220-1878-0358-0000-6d6d10adfc45", status_code=20100):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "tasks": [{
            "id": task_id,
            "status_code": status_code,
            "status_message": "Task Created." if status_code == 20100 else "Ok.",
            "result": None,
        }]
    }
    return resp


def _get_response(status_code, items=None):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    payload = {
        "tasks": [{
            "status_code": status_code,
            "status_message": "Task In Queue." if status_code == 40602 else "Ok.",
            "result": [{"items": items or []}] if status_code == 20000 else None,
        }]
    }
    resp.json.return_value = payload
    return resp


# Ítem grabado real (2026-08-21, Trustpilot, dominio avianca.com) — campos
# exactos que devuelve la API, texto recortado.
REAL_REVIEW_ITEM = {
    "type": "trustpilot_review_search",
    "url": "https://www.trustpilot.com/reviews/6a86135f53548f56eb58e043",
    "rating": {"rating_type": "Max5", "value": 1, "votes_count": None, "rating_max": 5},
    "verified": False,
    "language": "es",
    "timestamp": "2026-08-19 22:34:39 +00:00",
    "title": "Avianca protege solo sus propios intereses",
    "review_text": "Mi experiencia con Avianca fue profundamente decepcionante. "
                    "Solicitamos un reembolso y fue negado sin ninguna consideración.",
    "review_images": None,
    "user_profile": {
        "name": "Karol Jey",
        "url": "https://www.trustpilot.com/users/6a8613571910268463447104",
        "location": "US",
        "reviews_count": 1,
    },
    "responses": None,
}


@patch("scrapers.dataforseo_reviews.time.sleep")
@patch("scrapers.dataforseo_reviews.requests.get")
@patch("scrapers.dataforseo_reviews.requests.post")
def test_scrape_feliz_task_post_y_task_get_al_primer_intento(mock_post, mock_get, mock_sleep):
    mock_post.return_value = _post_response()
    mock_get.return_value = _get_response(20000, items=[REAL_REVIEW_ITEM])

    results = dataforseo_reviews.scrape(AVIANCA, since=None)

    assert len(results) == 1
    r = results[0]
    assert r["platform"] == "resena"
    assert r["rating"] == 1
    assert r["author"] == "Karol Jey"
    assert r["source_url"] == REAL_REVIEW_ITEM["url"]
    assert "decepcionante" in r["text"]
    assert r["published_at"].startswith("2026-08-19T22:34:39")


@patch("scrapers.dataforseo_reviews.time.sleep")
@patch("scrapers.dataforseo_reviews.requests.get")
@patch("scrapers.dataforseo_reviews.requests.post")
def test_reintenta_con_backoff_mientras_la_tarea_esta_en_cola(mock_post, mock_get, mock_sleep):
    """Verificado con datos reales: LATAM tardó 3 respuestas
    'Task In Queue' (40602) antes de la 4ta con status 20000."""
    mock_post.return_value = _post_response()
    mock_get.side_effect = [
        _get_response(40602),
        _get_response(40602),
        _get_response(40602),
        _get_response(20000, items=[REAL_REVIEW_ITEM]),
    ]

    results = dataforseo_reviews.scrape(LATAM, since=None)

    assert len(results) == 1
    assert mock_get.call_count == 4
    # Backoff creciente, no un sleep fijo — mismas esperas para las
    # primeras 4 llamadas que POLL_WAITS.
    esperas = [c.args[0] for c in mock_sleep.call_args_list]
    assert esperas == dataforseo_reviews.POLL_WAITS[:4]


@patch("scrapers.dataforseo_reviews.time.sleep")
@patch("scrapers.dataforseo_reviews.requests.get")
@patch("scrapers.dataforseo_reviews.requests.post")
def test_se_rinde_sin_lanzar_si_nunca_termina(mock_post, mock_get, mock_sleep):
    mock_post.return_value = _post_response()
    mock_get.return_value = _get_response(40602)  # siempre "en cola"

    results = dataforseo_reviews.scrape(AVIANCA, since=None)

    assert results == []
    assert mock_get.call_count == len(dataforseo_reviews.POLL_WAITS)


@patch("scrapers.dataforseo_reviews.requests.post")
def test_marca_sin_review_domain_no_llama_a_la_api(mock_post):
    marca_sin_dominio = {**AVIANCA, "review_domain": None}

    results = dataforseo_reviews.scrape(marca_sin_dominio, since=None)

    assert results == []
    mock_post.assert_not_called()


@patch("scrapers.dataforseo_reviews.time.sleep")
@patch("scrapers.dataforseo_reviews.requests.get")
@patch("scrapers.dataforseo_reviews.requests.post")
def test_since_filtra_del_lado_del_cliente(mock_post, mock_get, mock_sleep):
    mock_post.return_value = _post_response()
    mock_get.return_value = _get_response(20000, items=[REAL_REVIEW_ITEM])

    # La reseña grabada es del 2026-08-19.
    resultado_pasado = dataforseo_reviews.scrape(AVIANCA, since="2026-08-19")
    resultado_futuro = dataforseo_reviews.scrape(AVIANCA, since="2026-08-20")

    assert len(resultado_pasado) == 1
    assert resultado_futuro == []


@patch("scrapers.dataforseo_reviews.time.sleep")
@patch("scrapers.dataforseo_reviews.requests.get")
@patch("scrapers.dataforseo_reviews.requests.post")
def test_rating_no_numerico_queda_none_no_lanza(mock_post, mock_get, mock_sleep):
    item = {**REAL_REVIEW_ITEM, "rating": {"value": "no-numero"}}
    mock_post.return_value = _post_response()
    mock_get.return_value = _get_response(20000, items=[item])

    results = dataforseo_reviews.scrape(AVIANCA, since=None)

    assert results[0]["rating"] is None


@patch("scrapers.dataforseo_reviews.requests.post")
def test_task_post_con_status_de_error_no_llama_a_get(mock_post, ):
    mock_post.return_value = _post_response(status_code=40501)

    with patch("scrapers.dataforseo_reviews.requests.get") as mock_get:
        results = dataforseo_reviews.scrape(AVIANCA, since=None)
        mock_get.assert_not_called()

    assert results == []


@patch("scrapers.dataforseo_reviews.requests.post")
def test_usa_review_domain_de_la_marca_pasada(mock_post):
    mock_post.return_value = _post_response()
    with patch("scrapers.dataforseo_reviews.requests.get") as mock_get:
        mock_get.return_value = _get_response(20000, items=[])
        with patch("scrapers.dataforseo_reviews.time.sleep"):
            dataforseo_reviews.scrape(LATAM, since=None)

    payload = mock_post.call_args.kwargs["json"]
    assert payload[0]["domain"] == "latamairlines.com"
