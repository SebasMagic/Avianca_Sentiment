import json
from unittest.mock import MagicMock, patch

from config import get_brand
from pipeline import classifier

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")


def _api_response(payload):
    """Simula la envoltura de respuesta de DeepSeek."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]
    }
    return resp


OK = {
    "sentiment_positive": 0.0, "sentiment_negative": 0.9,
    "sentiment_neutral": 0.1, "emotion": "anger",
    "is_complaint": True, "complaint_driver": "equipaje",
}


def test_normaliza_respuesta_valida():
    out = classifier.normalize_result(OK)
    assert out["complaint_driver"] == "equipaje"
    assert out["is_complaint"] is True
    assert out["emotion"] == "anger"


def test_driver_invalido_se_mapea_a_otro():
    out = classifier.normalize_result({**OK, "complaint_driver": "wifi_del_avion"})
    assert out["complaint_driver"] == "otro"


def test_queja_sin_driver_recibe_otro():
    out = classifier.normalize_result({**OK, "complaint_driver": None})
    assert out["complaint_driver"] == "otro"


def test_no_queja_fuerza_driver_nulo():
    out = classifier.normalize_result({**OK, "is_complaint": False})
    assert out["complaint_driver"] is None


def test_emocion_invalida_se_mapea_a_neutral():
    out = classifier.normalize_result({**OK, "emotion": "euforia"})
    assert out["emotion"] == "neutral"


def test_sentiment_se_renormaliza_a_uno():
    out = classifier.normalize_result({
        **OK, "sentiment_positive": 2.0,
        "sentiment_negative": 2.0, "sentiment_neutral": 0.0,
    })
    total = (out["sentiment_positive"] + out["sentiment_negative"]
             + out["sentiment_neutral"])
    assert abs(total - 1.0) < 0.01
    # No solo debe sumar 1.0: las proporciones originales (1:1:0) deben
    # preservarse, no colapsar a cualquier combinación que sume 1.
    assert out["sentiment_positive"] == out["sentiment_negative"] == 0.5
    assert out["sentiment_neutral"] == 0.0


def test_emotion_no_hasheable_no_lanza_y_cae_a_neutral():
    out_list = classifier.normalize_result({**OK, "emotion": ["a", "b"]})
    assert out_list["emotion"] == "neutral"

    out_dict = classifier.normalize_result({**OK, "emotion": {"x": 1}})
    assert out_dict["emotion"] == "neutral"


def test_raw_no_dict_devuelve_none_no_neutral():
    assert classifier.normalize_result(None) is None
    assert classifier.normalize_result("basura") is None


def test_driver_lifemiles_ya_no_existe_se_mapea_a_otro():
    """lifemiles se renombró a programa_fidelidad (Tarea 3) — el nombre
    viejo ya no es un driver válido y debe caer a 'otro' como cualquier
    otro valor fuera de COMPLAINT_DRIVERS."""
    out = classifier.normalize_result({**OK, "complaint_driver": "lifemiles"})
    assert out["complaint_driver"] == "otro"


def test_driver_programa_fidelidad_es_valido():
    out = classifier.normalize_result({**OK, "complaint_driver": "programa_fidelidad"})
    assert out["complaint_driver"] == "programa_fidelidad"


def test_system_prompt_incluye_marca_y_programa_de_fidelidad_correctos():
    """El prompt ya no dice 'Avianca'/'LifeMiles' fijos — sale del perfil
    de la marca que se le pase (Tarea 3)."""
    prompt_avianca = classifier.build_system_prompt(AVIANCA)
    prompt_latam = classifier.build_system_prompt(LATAM)

    assert "aerolínea Avianca en Colombia" in prompt_avianca
    assert "LifeMiles" in prompt_avianca
    assert "LATAM Pass" not in prompt_avianca

    assert "aerolínea LATAM en Colombia" in prompt_latam
    assert "LATAM Pass" in prompt_latam
    assert "LifeMiles" not in prompt_latam


@patch("pipeline.classifier.requests.post")
def test_batch_feliz(mock_post):
    mock_post.return_value = _api_response([OK, OK])
    out = classifier.classify_texts(["texto uno", "texto dos"], AVIANCA)
    assert len(out) == 2
    assert all(o["complaint_driver"] == "equipaje" for o in out)
    assert mock_post.call_count == 1


@patch("pipeline.classifier.time.sleep")
@patch("pipeline.classifier.requests.post")
def test_longitud_desigual_no_hace_zip_y_cae_a_item_por_item(mock_post, mock_sleep):
    # 1º llamado (batch de 2) devuelve 1 objeto → inválido
    # 2º llamado (reintento del batch) devuelve 1 objeto → inválido otra vez
    # 3º y 4º llamados (item por item) devuelven 1 objeto cada uno → válidos
    mock_post.side_effect = [
        _api_response([OK]),
        _api_response([OK]),
        _api_response([OK]),
        _api_response([OK]),
    ]
    out = classifier.classify_texts(["texto uno", "texto dos"], AVIANCA)
    assert len(out) == 2
    assert all(o is not None for o in out)
    assert mock_post.call_count == 4


@patch("pipeline.classifier.requests.post")
def test_elemento_no_dict_en_batch_valido_no_se_cuela_como_neutral(mock_post):
    # El array JSON tiene la longitud correcta (2), así que _call_api NO
    # lanza y no hay reintento — pero el segundo elemento es null, no un
    # objeto. Antes del fix esto se colaba como {"is_complaint": False, ...}
    # (un neutral falso); ahora debe quedar None, sin disfrazarse.
    mock_post.return_value = _api_response([OK, None])
    out = classifier.classify_texts([
        "queja real sobre maleta perdida", "otra queja seria",
    ], AVIANCA)
    assert mock_post.call_count == 1
    assert out[0]["complaint_driver"] == "equipaje"
    assert out[1] is None


@patch("pipeline.classifier.requests.post")
def test_parsea_respuesta_envuelta_en_fences(mock_post):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {
        "content": "```json\n" + json.dumps([OK]) + "\n```"
    }}]}
    mock_post.return_value = resp
    out = classifier.classify_texts(["texto uno"], AVIANCA)
    assert out[0]["complaint_driver"] == "equipaje"


@patch("pipeline.classifier.time.sleep")
@patch("pipeline.classifier.requests.post")
def test_fallo_total_devuelve_none_no_neutral(mock_post, mock_sleep):
    mock_post.side_effect = Exception("boom")
    out = classifier.classify_texts(["texto uno"], AVIANCA)
    assert out == [None]


@patch("pipeline.classifier.requests.post")
def test_classify_texts_envia_el_prompt_de_la_marca_correcta(mock_post):
    """Extremo a extremo: classify_texts(texts, LATAM) debe mandar a
    DeepSeek un system prompt que nombra LATAM y LATAM Pass, no Avianca."""
    mock_post.return_value = _api_response([OK])
    classifier.classify_texts(["texto sobre LATAM"], LATAM)

    sent = mock_post.call_args.kwargs["json"]
    system_msg = sent["messages"][0]["content"]
    assert "aerolínea LATAM en Colombia" in system_msg
    assert "LATAM Pass" in system_msg
    assert "Avianca" not in system_msg
