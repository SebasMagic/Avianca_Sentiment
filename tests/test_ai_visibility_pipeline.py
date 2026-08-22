"""
pipeline/ai_visibility.py — orquesta captura + persistencia. Los tres
scrapers y la comparación se mockean (ya se prueban por su cuenta en
tests/test_dataforseo_ai_visibility.py, tests/test_dataforseo_ai_prompts.py
y tests/test_dataforseo_share_of_voice.py); acá solo importa que
pipeline/ai_visibility.py llame a cada uno y persista lo que devuelven.
"""
from unittest.mock import patch

from config import get_brand
from pipeline import ai_visibility
from store import db

AVIANCA = get_brand("Avianca")


def _visibilidad_fake(brand, **kw):
    return {
        "brand_metrics": [{
            "brand": brand["name"], "captured_at": "2026-08-22T00:00:00+00:00",
            "domain": brand["review_domain"], "platform": "google",
            "mentions": 100, "ai_search_volume": 5000,
            "source_endpoint": "target_metrics", "raw": {},
        }],
        "brand_sources": [{
            "brand": brand["name"], "captured_at": "2026-08-22T00:00:00+00:00",
            "cited_domain": "www.kayak.com.co", "mentions": 10,
            "ai_search_volume": 500, "is_own_domain": False,
            "is_competitor_domain": False, "source_endpoint": "target_metrics",
        }],
        "search_examples": [{
            "brand": brand["name"], "captured_at": "2026-08-22T00:00:00+00:00",
            "platform": "google_ai_overview", "question": "q", "answer": "a",
            "ai_search_volume": 100, "top_source_domain": "x.com",
            "top_source_url": "https://x.com", "raw": {},
        }],
    }


def _prompts_fake(brand, **kw):
    return [{
        "response": {
            "captured_at": "2026-08-22T00:00:00+00:00", "platform": "chat_gpt",
            "model": "gpt-4o-mini", "prompt": "¿Es confiable?",
            "prompt_scope": "brand", "subject_brand": brand["name"],
            "response_text": "Sí, es confiable.", "input_tokens": 10,
            "output_tokens": 20, "money_spent": 0.0006, "raw": {},
        },
        "mentions": [{
            "brand": brand["name"], "appears": True, "position": 1,
            "sentiment_positive": 0.8, "sentiment_negative": 0.1,
            "sentiment_neutral": 0.1, "emotion": "happiness",
            "classification_status": "classified",
        }],
    }]


def _sov_fake(brand, **kw):
    return [{
        "brand": brand["name"], "captured_at": "2026-08-22T00:00:00+00:00",
        "keyword": f"{brand['keyword'].lower()} reclamo", "intent": "problema",
        "engine": "google_ads", "search_volume": 100, "raw": {},
    }]


@patch("pipeline.ai_visibility.dataforseo_share_of_voice.scrape", side_effect=_sov_fake)
@patch("pipeline.ai_visibility.dataforseo_ai_prompts.scrape", side_effect=_prompts_fake)
@patch("pipeline.ai_visibility.dataforseo_ai_visibility.scrape", side_effect=_visibilidad_fake)
def test_run_persiste_las_tres_capturas(mock_vis, mock_prompts, mock_sov, tmp_db):
    resumen = ai_visibility.run(tmp_db, AVIANCA)

    assert resumen == {
        "brand_metrics": 1, "brand_sources": 1, "search_examples": 1,
        "prompt_responses": 1, "share_of_voice": 1,
    }
    assert len(db.ai_brand_metrics_for_brand(tmp_db, "Avianca")) == 1
    assert len(db.ai_brand_sources_for_brand(tmp_db, "Avianca")) == 1
    assert len(db.ai_search_mention_examples_for_brand(tmp_db, "Avianca")) == 1
    assert len(db.ai_prompt_responses_for_brand(tmp_db, "Avianca")) == 1
    assert len(db.search_share_of_voice_for_brand(tmp_db, "Avianca")) == 1


@patch("pipeline.ai_visibility.dataforseo_share_of_voice.scrape", side_effect=_sov_fake)
@patch("pipeline.ai_visibility.dataforseo_ai_prompts.scrape", side_effect=_prompts_fake)
@patch("pipeline.ai_visibility.dataforseo_ai_visibility.scrape", side_effect=_visibilidad_fake)
def test_run_registra_una_corrida_terminada(mock_vis, mock_prompts, mock_sov, tmp_db):
    ai_visibility.run(tmp_db, AVIANCA)

    fila = tmp_db.execute(
        "SELECT * FROM runs WHERE mode = 'ai_visibility' AND brand = 'Avianca'"
    ).fetchone()
    assert fila is not None
    assert fila["finished_at"] is not None


def _comparacion_fake(brand_names):
    return {
        "brand_metrics": [
            {"brand": "Avianca", "captured_at": "2026-08-22T00:00:00+00:00",
             "domain": "avianca.com", "platform": "google", "mentions": 1091,
             "ai_search_volume": 839350, "source_endpoint": "multi_target_metrics", "raw": {}},
            {"brand": "LATAM", "captured_at": "2026-08-22T00:00:00+00:00",
             "domain": "latamairlines.com", "platform": "google", "mentions": 1079,
             "ai_search_volume": 1037930, "source_endpoint": "multi_target_metrics", "raw": {}},
        ],
        "brand_sources": [],
    }


@patch("pipeline.ai_visibility.dataforseo_ai_visibility.scrape_comparison",
       side_effect=_comparacion_fake)
def test_run_comparison_persiste_ambas_marcas_de_un_solo_request(mock_scrape, tmp_db):
    resumen = ai_visibility.run_comparison(tmp_db)

    assert resumen == {"brand_metrics": 2, "brand_sources": 0}
    assert mock_scrape.call_count == 1
    avianca = db.ai_brand_metrics_for_brand(tmp_db, "Avianca")
    latam = db.ai_brand_metrics_for_brand(tmp_db, "LATAM")
    assert avianca[0]["source_endpoint"] == "multi_target_metrics"
    assert latam[0]["mentions"] == 1079
