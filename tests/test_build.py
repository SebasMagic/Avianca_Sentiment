import json

from dashboard import build


PAYLOAD = {
    "kpis": {"total": 2, "complaints": 1, "complaint_rate": 50.0,
             "net_sentiment": -70.0, "date_from": "2026-05-01",
             "date_to": "2026-05-02", "sources": 1},
    "timeline": [], "drivers": [], "driver_by_platform": [],
    "driver_trend": [],
    "sentiment": {"positive": 10.0, "negative": 80.0, "neutral": 10.0,
                  "classified_count": 2},
    "emotions": {"anger": 2}, "mentions": [], "top_complaints": [],
    "data_quality": {"total": 2, "unknown_date": 0, "unclassified": 0,
                     "filtered_total": 0, "short_text_last_run": 0,
                     "by_platform": {"tiktok": 2},
                     "by_month": {"2026-05": 2}, "missing_sources": ["twitter"]},
}


def test_render_inyecta_el_payload(tmp_path):
    plantilla = tmp_path / "t.html"
    plantilla.write_text(
        "<html><script>const DATA = __DASHBOARD_DATA__;</script></html>",
        encoding="utf-8",
    )
    html = build.render(PAYLOAD, str(plantilla))
    assert "__DASHBOARD_DATA__" not in html
    assert '"total": 2' in html or '"total":2' in html


def test_render_escapa_cierres_de_script(tmp_path):
    """Un texto con </script> dentro rompería el HTML si no se escapa."""
    plantilla = tmp_path / "t.html"
    plantilla.write_text("<script>const DATA = __DASHBOARD_DATA__;</script>",
                         encoding="utf-8")
    payload = {**PAYLOAD, "mentions": [{"text": "algo </script> malicioso"}]}
    html = build.render(payload, str(plantilla))
    assert "</script> malicioso" not in html
    assert "<\\/script>" in html


def test_render_produce_json_valido(tmp_path):
    plantilla = tmp_path / "t.html"
    plantilla.write_text("__DASHBOARD_DATA__", encoding="utf-8")
    html = build.render(PAYLOAD, str(plantilla))
    assert json.loads(html)["kpis"]["total"] == 2


def test_build_escribe_archivo_con_fecha(tmp_path, tmp_db):
    out = build.build(conn=tmp_db, out_dir=str(tmp_path))
    assert out.endswith(".html")
    assert "avianca_dashboard_" in out
    contenido = open(out, encoding="utf-8").read()
    assert "__DASHBOARD_DATA__" not in contenido
    assert "Chart" in contenido  # chart.js quedó inline
