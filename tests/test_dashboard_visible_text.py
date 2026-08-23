"""
Verifica que ningún texto que un usuario realmente VE en el dashboard
conserve el guion largo (—, em dash) — Cambio 2b (ajuste visual pedido por
el cliente: lo asocia con contenido generado por IA).

Un grep estático sobre template.html no sirve para esto: la mayoría de los
"—" del archivo viven en comentarios de código Python/JS/CSS (documentación
interna, explícitamente FUERA de alcance del cambio) o dentro de JS template
literals que arman texto en tiempo de ejecución — no hay forma de distinguir
esos dos casos sin ejecutar el JS de verdad. Este test renderiza el
dashboard real en un Chromium headless (Playwright), deja correr el script
de arriba a abajo (igual que un navegador real) y lee TODO lo que un usuario
vería: el texto del <body>, el título de la pestaña y cada atributo `title`
(tooltips) — exactamente los tres lugares que el enunciado pide cubrir.

Se salta con gracia (pytest.skip) si Playwright o su navegador Chromium no
están instalados en el entorno que corre la suite — no es una dependencia
del pipeline en sí (no está en requirements.txt), es una herramienta de
verificación visual que puede no estar disponible en todos lados.
"""
import sqlite3

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from config import REPORT_WINDOW_START, WEB_CHANNEL_RETIREMENT_REASON  # noqa: E402
from dashboard import build as dashboard_build  # noqa: E402
from store import db  # noqa: E402

EM_DASH = "—"  # — (U+2014). Nunca el guion corto "-" ni el signo menos "−" (U+2212).


def _chromium_disponible() -> bool:
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception:
        return False


if not _chromium_disponible():
    pytest.skip("Chromium de Playwright no disponible en este entorno", allow_module_level=True)


def _mention(idx, **kw):
    base = {
        "id": f"m-{idx}",
        "platform": "instagram",
        "source_url": f"https://instagram.com/p/{idx}",
        "text": f"Avianca perdió mi maleta numero {idx}, pésimo servicio",
        "author": f"user{idx}",
        "source_account": "avianca",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 5, "shares": 0, "comments_count": 0,
        "sentiment_positive": 0.0, "sentiment_negative": 0.9,
        "sentiment_neutral": 0.1, "emotion": "anger",
        "is_complaint": 1, "complaint_driver": "equipaje",
        "is_service_conversation": 1,
        "classification_status": "classified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
        "brand": "Avianca",
    }
    base.update(kw)
    return base


def _seed_rich(conn):
    run_id = db.start_run(conn, "backfill", REPORT_WINDOW_START, brand="Avianca")
    mentions = [
        # Repetida por el mismo autor (mismo author+text) -> repeat-badge,
        # con su tooltip ("×N").
        _mention(1, source_url="https://instagram.com/p/1a"),
        _mention(1, source_url="https://instagram.com/p/1b"),
        # Segundo driver operativo, para que renderRepHealth tenga con qué
        # contrastar "rechazo_marca".
        _mention(2, complaint_driver="rechazo_marca", author="user2",
                 text="Avianca son unos delincuentes"),
        # Con alcance propio (TikTok) -> bloque 7 "con alcance propio".
        _mention(3, platform="tiktok", author="user3", complaint_driver="demora",
                 text="El vuelo de Avianca se demoro horas", views=5000,
                 reach_source="propio", source_account=None),
        # Opinión positiva de servicio (no queja) -> conversación de
        # servicio true, complaint false.
        _mention(4, author="user4", is_complaint=0, complaint_driver=None,
                 is_service_conversation=1, sentiment_positive=0.9,
                 sentiment_negative=0.0, sentiment_neutral=0.1, emotion="love",
                 text="La mejor aerolinea en mi opinion"),
        # Reacción a campaña (no es conversación de servicio).
        _mention(5, author="user5", is_complaint=0, complaint_driver=None,
                 is_service_conversation=0, sentiment_positive=0.8,
                 sentiment_negative=0.0, sentiment_neutral=0.2, emotion="happiness",
                 text="Modo mundial activado"),
        # Fecha no confiable.
        _mention(6, author="user6", published_at=None, date_confidence="unknown",
                 is_complaint=0, complaint_driver=None),
        # Sin autor.
        _mention(7, author=None, is_complaint=0, complaint_driver=None,
                 source_account=None),
        # Sin link.
        _mention(8, author="user8", source_url=None, is_complaint=0, complaint_driver=None),
        # Sin clasificar todavía.
        _mention(9, author="user9", classification_status="unclassified",
                 sentiment_positive=None, sentiment_negative=None, sentiment_neutral=None,
                 emotion=None, is_complaint=0, complaint_driver=None,
                 is_service_conversation=0),
        # Fuera de la ventana de reporte.
        _mention(10, author="user10", published_at="2025-01-01T00:00:00+00:00",
                 is_complaint=0, complaint_driver=None),
        # Prensa.
        _mention(11, platform="prensa", author="eltiempo.com",
                 text="Avianca enfrenta demanda por cancelaciones masivas",
                 source_url="https://eltiempo.com/nota", is_complaint=1,
                 complaint_driver="cancelacion"),
        # Reseña de Trustpilot.
        _mention(12, platform="resena", author="Cliente Real",
                 text="Una estrella, pesimo servicio", source_url="https://trustpilot.com/r/1",
                 rating=1),
    ]
    db.upsert_mentions(conn, mentions, run_id)

    # Una excluida por irrelevancia social (TikTok, hashtag sin relación).
    irrelevante = _mention(13, platform="tiktok", author="user13",
                            text="latam es la region mas linda", is_complaint=0,
                            complaint_driver=None)
    db.upsert_mentions(conn, [irrelevante], run_id)
    fila_irr = [m for m in db.all_mentions(conn) if m["id"] == "m-13"][0]
    db.set_exclusion_reason(conn, fila_irr["id"], "sin_contexto_aeronautico")

    # Una retirada del canal web.
    web = _mention(14, platform="web", author="user14", text="agregador de vuelos",
                    is_complaint=0, complaint_driver=None)
    db.upsert_mentions(conn, [web], run_id)
    fila_web = [m for m in db.all_mentions(conn) if m["id"] == "m-14"][0]
    db.set_exclusion_reason(conn, fila_web["id"], WEB_CHANNEL_RETIREMENT_REASON)

    db.finish_run(conn, run_id, raw_count=20, filtered_count=3,
                   inserted_count=14, duplicate_count=1, short_text_count=2,
                   notes="ok")


def _render(conn, brand, tmp_path):
    path = dashboard_build.build(conn=conn, out_dir=str(tmp_path), brand=brand)
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8")


def _visible_offenders(html: str) -> list[str]:
    """Carga `html` en Chromium, deja correr el script del dashboard y
    devuelve una lista de fragmentos de texto REALMENTE visibles (texto del
    body, tooltips vía `title`, título de la pestaña) que todavía contienen
    un guion largo — vacía si no hay ninguno."""
    offenders = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")

        # El dashboard arranca con una sola sección visible (sidebar de
        # dos secciones más apéndice), y `innerText` NO incluye lo que
        # está en display:none: sin esto, el guion largo dejaría de
        # detectarse en toda la sección de IA.
        # La casilla "Ver todo en una sola página" existe justamente para
        # devolverle al documento su forma completa (Ctrl+F, impresión) y
        # acá recupera la cobertura del escaneo.
        # Se marca por JS y no con page.check(): debajo de 1288px de
        # viewport (el default de Playwright es 1280) el sidebar es un
        # cajón cerrado y la casilla no es clicable, pero el escaneo de
        # texto no depende del ancho.
        page.evaluate("() => { const c = document.getElementById('chkAllView');"
                      "        c.checked = true; c.dispatchEvent(new Event('change')); }")
        # Y se abre cada respuesta desplegable: su texto lo escribe un
        # modelo, así que es el que más riesgo tiene de traer un guion
        # largo (se normaliza al armar el payload, esto lo verifica de
        # punta a punta).
        page.evaluate("() => document.querySelectorAll('[data-aiv-toggle]').forEach(b => b.click())")
        page.wait_for_timeout(80)

        body_text = page.inner_text("body")
        for linea in body_text.splitlines():
            if EM_DASH in linea:
                offenders.append(f"body: {linea.strip()!r}")

        titles = page.eval_on_selector_all(
            "[title]", "els => els.map(e => e.getAttribute('title'))"
        )
        for t in titles:
            if t and EM_DASH in t:
                offenders.append(f"title (tooltip): {t!r}")

        page_title = page.title()
        if EM_DASH in page_title:
            offenders.append(f"<title>: {page_title!r}")

        browser.close()
    return offenders


@pytest.fixture
def tmp_db_file(tmp_path):
    conn = sqlite3.connect(tmp_path / "dashboard_test.db")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()


def test_dashboard_vacio_sin_guion_largo_en_texto_visible(tmp_db_file, tmp_path):
    """DB sin ninguna mención: dispara TODOS los mensajes de estado vacío
    (bloque 1, timeline, heatmap, sentiment, calidad, reseñas, prensa,
    visibilidad en IA, share of voice)."""
    html = _render(tmp_db_file, "Avianca", tmp_path / "out_empty")
    offenders = _visible_offenders(html)
    assert not offenders, "Guion largo en texto visible (dashboard vacío):\n" + "\n".join(offenders)


def test_dashboard_con_datos_sin_guion_largo_en_texto_visible(tmp_db_file, tmp_path):
    """DB con un dataset representativo: quejas con repetición (tooltip de
    ×N), driver de rechazo de marca, alcance propio, prensa, reseñas,
    exclusiones (irrelevancia social + retiro de canal web), menciones sin
    autor/sin link/sin fecha confiable/sin clasificar, y una corrida
    terminada con descartes — cubre la enorme mayoría de las cadenas que el
    cliente puede llegar a ver."""
    _seed_rich(tmp_db_file)
    html = _render(tmp_db_file, "Avianca", tmp_path / "out_rich")
    offenders = _visible_offenders(html)
    assert not offenders, "Guion largo en texto visible (dashboard con datos):\n" + "\n".join(offenders)
