from pipeline.normalizer import normalize

TEXTO = "Avianca me perdió la maleta en el aeropuerto de Bogotá otra vez"


def _m(**kw):
    base = {
        "platform": "tiktok",
        "text": TEXTO,
        "source_url": "https://x.com/1",
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.0,
        "sentiment_neutral": 1.0,
    }
    base.update(kw)
    return base


def test_fecha_presente_queda_exact():
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00")])
    assert out[0]["date_confidence"] == "exact"
    assert out[0]["published_at"] == "2026-05-01T10:00:00+00:00"


def test_fecha_ausente_queda_unknown_y_no_se_inventa():
    out = normalize([_m(published_at=None)])
    assert out[0]["date_confidence"] == "unknown"
    assert out[0]["published_at"] is None


def test_fecha_ausente_como_string_vacio_tambien_es_unknown():
    out = normalize([_m(published_at="")])
    assert out[0]["date_confidence"] == "unknown"
    assert out[0]["published_at"] is None


def test_confidence_explicito_del_scraper_se_respeta():
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00",
                        date_confidence="approx")])
    assert out[0]["date_confidence"] == "approx"


def test_descarta_textos_muy_cortos():
    assert normalize([_m(text="hola")]) == []


def test_normaliza_sentiment_que_no_suma_uno():
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00",
                        sentiment_positive=1.0,
                        sentiment_negative=1.0,
                        sentiment_neutral=2.0)])
    total = (out[0]["sentiment_positive"] + out[0]["sentiment_negative"]
             + out[0]["sentiment_neutral"])
    assert abs(total - 1.0) < 0.01


def test_confidence_explicito_se_ignora_si_no_hay_fecha_con_none():
    """Un scraper no puede afirmar 'approx' si no trajo fecha: sin fecha, siempre unknown."""
    out = normalize([_m(published_at=None, date_confidence="approx")])
    assert out[0]["date_confidence"] == "unknown"
    assert out[0]["published_at"] is None


def test_confidence_explicito_se_ignora_si_no_hay_fecha_con_string_vacio():
    """Un scraper no puede afirmar 'approx' si no trajo fecha (string vacío): sin fecha, siempre unknown."""
    out = normalize([_m(published_at="", date_confidence="approx")])
    assert out[0]["date_confidence"] == "unknown"
    assert out[0]["published_at"] is None


def test_mencion_sin_claves_de_sentiment_no_finge_neutralidad():
    """Sin datos de sentiment el resultado es (0,0,0), no un 1.0 neutral inventado.
    La autoridad sobre si algo fue analizado es classification_status."""
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00",
                        sentiment_positive=None,
                        sentiment_negative=None,
                        sentiment_neutral=None)])
    assert out[0]["sentiment_positive"] == 0.0
    assert out[0]["sentiment_negative"] == 0.0
    assert out[0]["sentiment_neutral"] == 0.0
