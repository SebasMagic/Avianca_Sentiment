import json
from unittest.mock import MagicMock, patch

from pipeline import classifier


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


@patch("pipeline.classifier.requests.post")
def test_batch_feliz(mock_post):
    mock_post.return_value = _api_response([OK, OK])
    out = classifier.classify_texts(["texto uno", "texto dos"])
    assert len(out) == 2
    assert all(o["complaint_driver"] == "equipaje" for o in out)
    assert mock_post.call_count == 1


@patch("pipeline.classifier.requests.post")
def test_longitud_desigual_no_hace_zip_y_cae_a_item_por_item(mock_post):
    # 1º llamado (batch de 2) devuelve 1 objeto → inválido
    # 2º llamado (reintento del batch) devuelve 1 objeto → inválido otra vez
    # 3º y 4º llamados (item por item) devuelven 1 objeto cada uno → válidos
    mock_post.side_effect = [
        _api_response([OK]),
        _api_response([OK]),
        _api_response([OK]),
        _api_response([OK]),
    ]
    out = classifier.classify_texts(["texto uno", "texto dos"])
    assert len(out) == 2
    assert all(o is not None for o in out)
    assert mock_post.call_count == 4


@patch("pipeline.classifier.requests.post")
def test_parsea_respuesta_envuelta_en_fences(mock_post):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {
        "content": "```json\n" + json.dumps([OK]) + "\n```"
    }}]}
    mock_post.return_value = resp
    out = classifier.classify_texts(["texto uno"])
    assert out[0]["complaint_driver"] == "equipaje"


@patch("pipeline.classifier.requests.post")
def test_fallo_total_devuelve_none_no_neutral(mock_post):
    mock_post.side_effect = Exception("boom")
    out = classifier.classify_texts(["texto uno"])
    assert out == [None]
