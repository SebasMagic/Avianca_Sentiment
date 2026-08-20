import json
from pathlib import Path

import pytest

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
                     "filtered_last_run": 0, "short_text_last_run": 0,
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


def test_render_embebe_el_logo_como_data_uri(tmp_path):
    """El logo se inyecta como data URI base64, mismo patrón que __CHARTJS__,
    para que el archivo siga siendo autocontenido y funcione sin internet."""
    plantilla = tmp_path / "t.html"
    plantilla.write_text('<img src="__AVIANCA_LOGO__" alt="Avianca">', encoding="utf-8")
    html = build.render(PAYLOAD, str(plantilla))
    assert "__AVIANCA_LOGO__" not in html
    assert "data:image/png;base64," in html


def test_build_escribe_archivo_con_fecha(tmp_path, tmp_db):
    out = build.build(conn=tmp_db, out_dir=str(tmp_path))
    assert out.endswith(".html")
    assert "avianca_dashboard_" in out
    contenido = open(out, encoding="utf-8").read()
    assert "__DASHBOARD_DATA__" not in contenido
    assert "Chart" in contenido  # chart.js quedó inline


# ── Multi-marca (Tarea 2/3): build por marca, título/color/logo del perfil ─

def test_build_nombre_de_archivo_sale_de_la_marca(tmp_path, tmp_db):
    out = build.build(conn=tmp_db, out_dir=str(tmp_path), brand="LATAM")
    assert "latam_dashboard_" in out
    assert "avianca" not in Path(out).name


def test_build_marca_desconocida_falla_temprano(tmp_path, tmp_db):
    with pytest.raises(ValueError):
        build.build(conn=tmp_db, out_dir=str(tmp_path), brand="Delta")


def test_render_titulo_y_color_avianca_salen_del_perfil():
    """Sin --brand (default), el look de Avianca se conserva exactamente:
    su rojo de marca y su logo PNG embebido — no un wordmark."""
    html = build.render(PAYLOAD)
    assert "<title>Avianca — Social Listening</title>" in html
    assert "--brand:#F62839;" in html
    assert "--brand-ink:#C81030;" in html
    assert "data:image/png;base64," in html
    assert '<span class="brand-wordmark"' not in html  # ningún wordmark USADO — sigue siendo el <img>
    assert "__BRAND_" not in html  # ningún marcador de marca sin sustituir


def test_render_titulo_y_color_latam_salen_del_perfil():
    html = build.render(PAYLOAD, brand_name="LATAM")
    assert "<title>LATAM — Social Listening</title>" in html
    assert "--brand:#1B0088;" in html
    assert "__BRAND_" not in html


def test_render_latam_usa_wordmark_no_placeholder(tmp_path):
    """LATAM no tiene archivo de logo (config.BRANDS['LATAM']['logo'] es
    None): el encabezado debe resolverse con un wordmark tipográfico
    propio, nunca con un <img> roto ni un cuadro vacío."""
    html = build.render(PAYLOAD, brand_name="LATAM")
    assert 'class="brand-wordmark"' in html
    assert "LATAM" in html
    # Nada de <img> apuntando a un archivo que no existe.
    assert '<img class="brand-logo"' not in html


def test_render_footer_y_encabezado_usan_el_nombre_de_marca():
    html_avianca = build.render(PAYLOAD)
    assert "Avianca · Social Listening" in html_avianca

    html_latam = build.render(PAYLOAD, brand_name="LATAM")
    assert "LATAM · Social Listening" in html_latam


def test_render_web_platform_color_no_cambia_por_marca():
    """El azul de la plataforma "web" en los gráficos es un identificador
    de plataforma, no de marca — debe quedar igual para las dos marcas,
    incluida LATAM (cuyo color de marca también es azul)."""
    html_avianca = build.render(PAYLOAD)
    html_latam = build.render(PAYLOAD, brand_name="LATAM")
    assert "web:'#2A78D6'" in html_avianca
    assert "web:'#2A78D6'" in html_latam


def test_driver_label_programa_fidelidad_reemplaza_a_lifemiles():
    """Tarea 4: el label huérfano 'lifemiles: LifeMiles' se renombra a
    'programa_fidelidad', con una etiqueta neutra que sirve para ambas
    marcas — el nombre concreto del programa vive en el perfil, no acá."""
    html = build.render(PAYLOAD)
    assert "programa_fidelidad:'Programa de fidelidad'" in html
    # El código (no los comentarios explicativos) ya no referencia la clave
    # vieja como entrada de DRIVER_LABEL — se busca el patrón de código
    # exacto, no la palabra suelta (que sí aparece, a propósito, en un
    # comentario que documenta el rename).
    assert "lifemiles:'LifeMiles'" not in html


# ── Derivación de --brand-ink (contraste WCAG AA, criterio del skill dataviz) ─

def test_derive_ink_preserva_el_valor_calibrado_de_avianca():
    """El rojo de Avianca (#F62839) no llega a 4.5:1 como texto — su ink ya
    fue calibrado a mano en producción (#C81030, ~5.9:1) y debe
    preservarse tal cual, no recalcularse con un resultado distinto."""
    assert build._derive_ink("#F62839") == "#C81030"


def test_derive_ink_reutiliza_el_color_si_ya_sirve_como_texto():
    """El azul de LATAM (#1B0088) ya tiene ~15:1 de contraste sobre blanco
    — no necesita una variante oscurecida, se reutiliza tal cual."""
    assert build._derive_ink("#1B0088") == "#1B0088"


def test_derive_ink_oscurece_un_color_generico_que_no_sirve_como_texto():
    """Cualquier color de marca futuro que no alcance 4.5:1 debe
    oscurecerse hasta cumplirlo — no queda hardcodeado a Avianca/LATAM."""
    claro = "#FFAA00"
    assert build._contrast_ratio(claro, "#FFFFFF") < 4.5
    ink = build._derive_ink(claro)
    assert build._contrast_ratio(ink, "#FFFFFF") >= 4.5
