from dashboard import aggregate
from store import db


def _m(idx, **kw):
    base = {
        "id": f"m-{idx}",
        "platform": "tiktok",
        "source_url": f"https://x.com/{idx}",
        "text": f"Avianca comentario numero {idx} sobre el servicio",
        "author": "user",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10, "shares": 1, "comments_count": 2,
        "sentiment_positive": 0.1, "sentiment_negative": 0.8,
        "sentiment_neutral": 0.1, "emotion": "anger",
        "is_complaint": 1, "complaint_driver": "equipaje",
        "classification_status": "classified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_kpis_basicos(tmp_db):
    _seed(tmp_db, [_m(1), _m(2, is_complaint=0, complaint_driver=None)])
    p = aggregate.build_payload(tmp_db)
    assert p["kpis"]["total"] == 2
    assert p["kpis"]["complaints"] == 1
    assert p["kpis"]["complaint_rate"] == 50.0


def test_timeline_excluye_fechas_desconocidas(tmp_db):
    _seed(tmp_db, [
        _m(1),
        _m(2, published_at=None, date_confidence="unknown"),
    ])
    p = aggregate.build_payload(tmp_db)
    fechas = [punto["date"] for punto in p["timeline"]]
    assert fechas == ["2026-05-01"]
    assert p["timeline"][0]["counts"]["tiktok"] == 1


def test_sentiment_excluye_unclassified(tmp_db):
    _seed(tmp_db, [
        _m(1, sentiment_negative=1.0, sentiment_positive=0.0, sentiment_neutral=0.0),
        _m(2, classification_status="unclassified",
           sentiment_negative=None, sentiment_positive=None, sentiment_neutral=None),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["sentiment"]["negative"] == 100.0
    assert p["sentiment"]["classified_count"] == 1


def test_drivers_ordenados_por_volumen(tmp_db):
    _seed(tmp_db, [
        _m(1, complaint_driver="equipaje"),
        _m(2, complaint_driver="equipaje"),
        _m(3, complaint_driver="demora"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["drivers"][0]["driver"] == "equipaje"
    assert p["drivers"][0]["count"] == 2
    assert p["drivers"][1]["driver"] == "demora"


def test_driver_por_plataforma(tmp_db):
    _seed(tmp_db, [
        _m(1, platform="tiktok", complaint_driver="equipaje"),
        _m(2, platform="instagram", complaint_driver="equipaje"),
    ])
    p = aggregate.build_payload(tmp_db)
    celda = [c for c in p["driver_by_platform"]
             if c["driver"] == "equipaje" and c["platform"] == "instagram"]
    assert celda[0]["count"] == 1


def test_top_complaints_ordenadas_por_engagement(tmp_db):
    _seed(tmp_db, [
        _m(1, likes=5, shares=0, comments_count=0),
        _m(2, likes=500, shares=100, comments_count=50),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["top_complaints"][0]["engagement"] == 650
    assert p["top_complaints"][0]["id"] == "m-2"


def test_data_quality_reporta_huecos(tmp_db):
    _seed(tmp_db, [
        _m(1),
        _m(2, published_at=None, date_confidence="unknown"),
        _m(3, classification_status="unclassified"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["unknown_date"] == 1
    assert p["data_quality"]["unclassified"] == 1
    assert p["data_quality"]["total"] == 3


def test_mentions_incluye_todo_para_la_tabla(tmp_db):
    _seed(tmp_db, [_m(1), _m(2)])
    p = aggregate.build_payload(tmp_db)
    assert len(p["mentions"]) == 2
    assert set(p["mentions"][0]) >= {
        "id", "platform", "text", "author", "published_at",
        "source_url", "complaint_driver", "is_complaint", "engagement",
    }
