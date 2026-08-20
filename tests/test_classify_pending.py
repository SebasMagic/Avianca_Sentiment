from unittest.mock import patch

from pipeline import classify_pending
from store import db

CLASIFICADO = {
    "sentiment_positive": 0.0, "sentiment_negative": 0.9,
    "sentiment_neutral": 0.1, "emotion": "anger",
    "is_complaint": True, "complaint_driver": "equipaje",
}


def _mention(idx):
    return {
        "id": f"m-{idx}",
        "platform": "tiktok",
        "source_url": f"https://x.com/{idx}",
        "text": f"Avianca me perdió la maleta numero {idx} en Bogotá",
        "author": "user",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 0, "shares": 0, "comments_count": 0,
        "classification_status": "unclassified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }


@patch("pipeline.classify_pending.classify_texts")
def test_clasifica_todo_lo_pendiente(mock_classify, tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(1), _mention(2)], run_id)
    mock_classify.return_value = [CLASIFICADO, CLASIFICADO]

    res = classify_pending.run(tmp_db)

    assert res == {"pendientes": 2, "clasificadas": 2, "fallidas": 0}
    assert db.pending_classification(tmp_db) == []
    assert all(m["complaint_driver"] == "equipaje" for m in db.all_mentions(tmp_db))


@patch("pipeline.classify_pending.classify_texts")
def test_los_none_quedan_unclassified(mock_classify, tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(1), _mention(2)], run_id)
    mock_classify.return_value = [CLASIFICADO, None]

    res = classify_pending.run(tmp_db)

    assert res == {"pendientes": 2, "clasificadas": 1, "fallidas": 1}
    assert len(db.pending_classification(tmp_db)) == 1


@patch("pipeline.classify_pending.classify_texts")
def test_sin_pendientes_no_llama_al_modelo(mock_classify, tmp_db):
    res = classify_pending.run(tmp_db)
    assert res == {"pendientes": 0, "clasificadas": 0, "fallidas": 0}
    mock_classify.assert_not_called()
