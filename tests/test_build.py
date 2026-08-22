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
    assert "<title>Avianca: Social Listening</title>" in html
    assert "--brand:#F62839;" in html
    assert "--brand-ink:#C81030;" in html
    assert "data:image/png;base64," in html
    assert '<span class="brand-wordmark"' not in html  # ningún wordmark USADO — sigue siendo el <img>
    assert "__BRAND_" not in html  # ningún marcador de marca sin sustituir


def test_render_titulo_y_color_latam_salen_del_perfil():
    html = build.render(PAYLOAD, brand_name="LATAM")
    assert "<title>LATAM: Social Listening</title>" in html
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


def test_render_ya_no_declara_color_ni_marcador_para_web():
    """Cambio 1 (retiro del canal web): el marcador __BRAND_WEB_COLOR__ y
    la entrada 'web' de PLT_COLOR salieron de la plantilla — no queda
    ningún color declarado para una plataforma que ya no se reporta, ni
    en Avianca ni en LATAM (cuyo color de marca también es azul, el
    motivo original por el que 'web' necesitaba un azul propio)."""
    html_avianca = build.render(PAYLOAD)
    html_latam = build.render(PAYLOAD, brand_name="LATAM")
    assert "__BRAND_WEB_COLOR__" not in html_avianca
    assert "__BRAND_WEB_COLOR__" not in html_latam
    assert "web:" not in html_avianca
    assert "web:" not in html_latam


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


# ── Tarea 1 (revisión 2026-08-20): tabla de menciones responsive, bloque 6 ──
# La tabla tenía 13 columnas y no cabía en 1440px sin scroll horizontal. El
# rediseño vive entero en template.html (HTML/CSS/JS) — build.py y
# aggregate.py no se tocan — así que estas pruebas verifican, sobre el HTML
# ya renderizado por build.render(), que el marcado nuevo (vista compacta
# por defecto + toggle de detalle) quedó en su lugar. No hay runtime de JS
# en esta suite (es Python puro, como el resto del archivo): se prueba la
# forma del HTML/CSS/JS servido, no su ejecución en un navegador — el
# comportamiento en vivo (toggle, sorting, degradado a tarjetas) se
# verificó aparte con Playwright (ver .superpowers/tabla-responsive.md).

def test_boton_de_detalle_arranca_en_estado_compacto():
    """El toggle "Ver detalle de engagement" existe y arranca sin activar
    — la vista por defecto es la compacta (Tarea 1)."""
    html = build.render(PAYLOAD)
    assert 'id="btnDetalle"' in html
    assert 'aria-pressed="false"' in html
    assert ">Ver detalle de engagement<" in html


def test_columnas_desglosadas_quedan_marcadas_detail_col_pero_siguen_siendo_th_data_sort():
    """Las 6 columnas que el usuario pidió desglosadas (Visib. post, Likes,
    Coment., Shares, Saves, Engagement) no se eliminan — quedan detrás del
    toggle, pero cada una sigue siendo un <th data-sort> real y ordenable,
    no un elemento sacado del DOM ni con el ordenamiento roto."""
    html = build.render(PAYLOAD)
    columnas_desglosadas = [
        "post_reach", "likes", "comments_count", "shares", "saves", "engagement",
    ]
    for col in columnas_desglosadas:
        assert f'class="sortable detail-col" data-sort="{col}"' in html, col


def test_interacciones_es_columna_compacta_no_desglosada():
    """Interacciones (el agregado likes+comentarios+shares+saves) es una de
    las columnas que sobreviven a la vista compacta — no debe llevar la
    clase detail-col como las 6 desglosadas."""
    html = build.render(PAYLOAD)
    assert 'data-sort="interactions"' in html
    assert 'class="sortable detail-col" data-sort="interactions"' not in html
    assert '<th class="sortable" data-sort="interactions">Interacciones' in html


def test_autor_y_texto_comparten_celda_pero_siguen_ordenables_por_separado():
    """Autor y Texto comparten una sola cabecera <th> (Tarea 1: "pueden
    compartir celda") pero cada uno sigue siendo su propio <span
    data-sort> ordenable — no se perdió la capacidad de ordenar por
    cualquiera de los dos por separado."""
    html = build.render(PAYLOAD)
    assert '<th class="sortable multi">' in html
    assert '<span class="sort-seg" data-sort="author">Autor' in html
    assert '<span class="sort-seg" data-sort="text">Texto' in html
    # El cuerpo junta autor+texto en una sola celda con clases propias.
    assert 'class="author-text"' in html
    assert 'class="at-author"' in html
    assert 'class="at-text"' in html


def test_fecha_compacta_reemplaza_el_formato_largo_en_la_tabla():
    """"11 de ago de 26" gastaba demasiado espacio — la tabla usa
    fmtDateShort (DD/MM/AA) en vez del fmtDate largo que sigue usando el
    resto del dashboard (encabezado, tarjetas de quejas, etc.)."""
    html = build.render(PAYLOAD)
    assert "function fmtDateShort(iso)" in html
    assert "fmtDateShort(m.published_at)" in html


def test_media_query_de_tarjetas_moviles_existe_para_el_bloque_6():
    """Debajo de 680px la tabla se degrada a tarjetas apiladas (Tarea 2)
    en vez de comprimir columnas hasta volverse ilegible."""
    html = build.render(PAYLOAD)
    assert "@media (max-width:680px)" in html
    assert "content:attr(data-label)" in html


# ── stage_for_deploy: nombre de archivo correcto por marca (Tarea 4) ─────
#
# Bug real: --deploy SIEMPRE escribía deploy/index.html sin importar qué
# marca se hubiera construido — build.py --deploy --brand LATAM pisaba el
# dashboard de Avianca, y deploy/latam.html se venía copiando a mano por
# fuera del script.

def test_stage_for_deploy_sin_marca_escribe_index_html(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DEPLOY_DIR", tmp_path)
    origen = tmp_path / "avianca_dashboard_2026-08-22.html"
    origen.write_text("<html>avianca</html>", encoding="utf-8")

    destino = build.stage_for_deploy(str(origen))

    assert destino.endswith("index.html")
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "<html>avianca</html>"


def test_stage_for_deploy_latam_escribe_latam_html_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DEPLOY_DIR", tmp_path)
    origen = tmp_path / "latam_dashboard_2026-08-22.html"
    origen.write_text("<html>latam</html>", encoding="utf-8")

    destino = build.stage_for_deploy(str(origen), brand="LATAM")

    assert destino.endswith("latam.html")
    assert (tmp_path / "latam.html").read_text(encoding="utf-8") == "<html>latam</html>"
    assert not (tmp_path / "index.html").exists()  # no pisa el de Avianca


def test_stage_for_deploy_avianca_y_latam_conviven_sin_pisarse(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DEPLOY_DIR", tmp_path)
    avianca_html = tmp_path / "avianca_dashboard_2026-08-22.html"
    avianca_html.write_text("<html>avianca</html>", encoding="utf-8")
    latam_html = tmp_path / "latam_dashboard_2026-08-22.html"
    latam_html.write_text("<html>latam</html>", encoding="utf-8")

    build.stage_for_deploy(str(avianca_html))
    build.stage_for_deploy(str(latam_html), brand="LATAM")

    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "<html>avianca</html>"
    assert (tmp_path / "latam.html").read_text(encoding="utf-8") == "<html>latam</html>"
