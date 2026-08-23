"""
Comportamiento en vivo del dashboard: lo que solo se puede comprobar
ejecutando el JS en un navegador de verdad. Mismo patrón (y misma salida
con gracia si Chromium no está instalado) que
tests/test_dashboard_visible_text.py.

Cubre los dos gestos nuevos que el cliente pidió:
  1. El desplegable "Leer la respuesta completa" de las tarjetas de
     prompt (bloques 10c/10d) y de los ejemplos indexados (10e).
  2. El sidebar de dos secciones: paneles que se muestran y ocultan,
     anclas que cambian de sección, y la casilla "Ver todo en una sola
     página".

Los tests de tests/test_build*.py siguen mirando la FORMA del HTML
servido; este mira su COMPORTAMIENTO.
"""
import sqlite3

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from dashboard import build  # noqa: E402
from dashboard.aggregate import build_payload  # noqa: E402
from store import db  # noqa: E402


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


LARGO = (
    "Avianca es una aerolínea colombiana con más de cien años de historia. "
    "LATAM compite en las mismas rutas regionales. "
) * 12
CORTO = LARGO[:200]


def _prompt(prompt: str, response_full: str, excerpt: str | None = None) -> dict:
    return {
        "prompt": prompt, "model": "gpt-4o-mini-2024-07-18",
        "appears": True, "position": 1, "sentiment": "neutral",
        "excerpt": excerpt if excerpt is not None else response_full[:380],
        "response_full": response_full,
        "captured_at": "2026-08-22T00:00:00+00:00",
    }


def _payload_base(tmp_path) -> dict:
    """Payload real de dashboard.aggregate sobre una base vacía. Se arma
    con el agregador de verdad (no con un diccionario a mano) para que la
    forma de cada clave sea exactamente la que consume la plantilla: un
    fixture escrito a mano se desincroniza en silencio y el JS revienta
    en tiempo de ejecución, no en el test."""
    conn = sqlite3.connect(tmp_path / "interaccion.db")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    try:
        return build_payload(conn, brand="Avianca")
    finally:
        conn.close()


PAYLOAD_IA = {
    "ai_visibility": {
        "brand": "Avianca",
        "own": {"brand": "Avianca", "mentions": 1091, "ai_search_volume": 839350,
                "domain": "avianca.com", "captured_at": "2026-08-22T00:00:00+00:00",
                "source_endpoint": "target_metrics", "sources": []},
        "competitors": [{"brand": "LATAM", "mentions": 1079,
                          "ai_search_volume": 1037930, "sources": []}],
        "missing_competitors": [],
        "category_prompts": [_prompt("¿Cuál es la mejor aerolínea?", LARGO)],
        "brand_prompts": [_prompt("¿Es confiable Avianca?", CORTO, excerpt=CORTO)],
        "search_examples": [{
            "question": "avianca check in", "answer": LARGO[:380],
            "answer_full": LARGO, "platform": "google_ai_overview",
            "ai_search_volume": 110000, "source_domain": "www.avianca.com",
            "source_url": "https://www.avianca.com",
            "captured_at": "2026-08-22T00:00:00+00:00",
        }],
        "has_metrics": True, "has_prompts": True, "has_search_examples": True,
        "captured_at": "2026-08-22T00:00:00+00:00",
    },
    "share_of_voice": {
        "brand": "Avianca",
        "by_engine": {"google_ads": {"problema": 890, "comercial": 311920,
                                      "problem_pct": 0.28, "problem_one_in": 351,
                                      "keywords": []}},
        "competitors": [{"brand": "LATAM", "captured_at": None, "by_engine": {
            "google_ads": {"problema": 80, "comercial": 123390,
                            "problem_pct": 0.06, "problem_one_in": 1543,
                            "keywords": []}}}],
        "missing_competitors": [],
        "has_data": True, "captured_at": "2026-08-22T00:00:00+00:00",
    },
}


@pytest.fixture(scope="module")
def html_dashboard(tmp_path_factory) -> str:
    return build.render({**_payload_base(tmp_path_factory.mktemp("dash")), **PAYLOAD_IA})


@pytest.fixture(scope="module")
def pagina(html_dashboard):
    """Una sola pestaña de Chromium para todo el módulo: levantar el
    navegador por test multiplicaría por diez el tiempo de la suite."""
    html = html_dashboard
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errores = []
        page.on("pageerror", lambda e: errores.append(str(e)))
        page.set_content(html, wait_until="load")
        page.wait_for_timeout(200)
        assert not errores, f"El script del dashboard lanzó errores: {errores}"
        yield page
        browser.close()


@pytest.fixture
def pagina_ai(pagina):
    """Los bloques de IA viven en el panel 2, que arranca oculto: sin
    activarlo, sus controles no son clicables ni tienen texto visible."""
    pagina.locator('.nav-sec[data-panel="panel-ai"]').click()
    yield pagina
    pagina.locator('.nav-sec[data-panel="panel-social"]').click()


# ── desplegable de respuesta completa ────────────────────────────────────

def test_solo_las_respuestas_truncadas_traen_el_control(pagina_ai):
    """La tarjeta de categoría tiene texto de sobra (control), la de marca
    cabía entera en el excerpt (sin control): esa asimetría es justo lo
    que evita una flechita que no despliega nada."""
    assert pagina_ai.locator("#aivCategory [data-aiv-toggle]").count() == 1
    assert pagina_ai.locator("#aivBrandPrompts [data-aiv-toggle]").count() == 0
    assert pagina_ai.locator("#aivSearchExamples [data-aiv-toggle]").count() == 1


def test_el_control_abre_y_cierra_la_respuesta_completa(pagina_ai):
    boton = pagina_ai.locator("#aivCategory [data-aiv-toggle]")
    panel = pagina_ai.locator("#aivCategory .aiv-resp")

    assert boton.get_attribute("aria-expanded") == "false"
    assert not panel.is_visible()
    assert boton.inner_text().strip() == "Leer la respuesta completa"

    boton.click()
    assert boton.get_attribute("aria-expanded") == "true"
    assert panel.is_visible()
    assert boton.inner_text().strip() == "Ocultar la respuesta completa"
    # Abierto, el excerpt recortado se retira: el texto completo empieza
    # con las mismas palabras, así que se lee como si hubiera crecido.
    assert not pagina_ai.locator("#aivCategory .aiv-prompt-excerpt").is_visible()

    boton.click()
    assert boton.get_attribute("aria-expanded") == "false"
    assert not panel.is_visible()
    assert pagina_ai.locator("#aivCategory .aiv-prompt-excerpt").is_visible()


def test_la_respuesta_desplegada_trae_el_texto_completo_no_el_excerpt(pagina_ai):
    pagina_ai.locator("#aivCategory [data-aiv-toggle]").click()
    texto = pagina_ai.locator("#aivCategory .aiv-resp-txt").inner_text()
    pagina_ai.locator("#aivCategory [data-aiv-toggle]").click()

    assert len(texto) > 380
    assert "cien años de historia" in texto


def test_resalta_la_marca_propia_y_al_competidor_con_conteo(pagina_ai):
    pagina_ai.locator("#aivCategory [data-aiv-toggle]").click()
    propias = pagina_ai.locator("#aivCategory .aiv-resp .aiv-mark-own").count()
    rivales = pagina_ai.locator("#aivCategory .aiv-resp .aiv-mark-rival").count()
    meta = pagina_ai.locator("#aivCategory .aiv-resp-meta").inner_text()
    pagina_ai.locator("#aivCategory [data-aiv-toggle]").click()

    assert propias == 12  # una "Avianca" por repetición de LARGO
    assert rivales == 12
    assert "Avianca: 12 menciones" in meta
    assert "LATAM: 12 menciones" in meta


def test_declara_que_modelo_respondio(pagina_ai):
    """`model` viajaba en el payload desde siempre y no se pintaba en
    ninguna parte: no se sabía qué modelo dijo qué."""
    pagina_ai.locator("#aivCategory [data-aiv-toggle]").click()
    src = pagina_ai.locator("#aivCategory .aiv-resp-src").inner_text()
    pagina_ai.locator("#aivCategory [data-aiv-toggle]").click()

    assert "ChatGPT" in src
    assert "gpt-4o-mini-2024-07-18" in src


def test_el_control_es_un_boton_real_operable_con_teclado(pagina_ai):
    """<button> y no <div>: ya es enfocable con Tab y ya responde a Enter
    y Espacio, sin manejadores de teclado propios."""
    boton = pagina_ai.locator("#aivCategory [data-aiv-toggle]")
    assert boton.evaluate("b => b.tagName") == "BUTTON"
    boton.focus()
    pagina_ai.keyboard.press("Enter")
    assert boton.get_attribute("aria-expanded") == "true"
    pagina_ai.keyboard.press(" ")
    assert boton.get_attribute("aria-expanded") == "false"


# ── textos explicativos (pedidos 1 y 3) ──────────────────────────────────

def test_el_bloque_de_menciones_en_ia_explica_que_se_mide(pagina_ai):
    """Pedido 1: "no entiendo esto, cómo se lee". Bajada (qué es cada
    número) arriba y nota de lectura (qué dice la comparación) abajo."""
    bajada = pagina_ai.locator("#aivCompare .aiv-bajada").inner_text()
    lectura = pagina_ai.locator("#aivCompare .aiv-lectura").inner_text()

    assert "cuántas veces la marca aparece nombrada" in bajada
    assert "volumen asociado" in bajada
    # La nota se arma con los números del payload, no con una frase fija.
    assert "1.091" in lectura and "1.079" in lectura
    assert "1.037.930" in lectura and "839.350" in lectura
    assert "LATAM" in lectura
    assert "mide alcance" in lectura


def test_share_of_voice_titula_con_1_de_cada_n_y_el_competidor_al_lado(pagina_ai):
    """0,28% y 0,06% se leen los dos como "casi nada"; 351 contra 1.543 se
    lee como una diferencia de escala. Y sin el competidor en la misma
    tarjeta el bloque no es interpretable."""
    ratios = pagina_ai.locator("#sovCard .sov-ratio-row").all_inner_texts()
    assert any("1 de cada 351" in r and "Avianca" in r for r in ratios)
    assert any("1 de cada 1.543" in r and "LATAM" in r for r in ratios)


def test_la_razon_de_share_of_voice_cuadra_con_los_numeros_que_muestra(pagina_ai):
    """1.543 / 351 = 4,4. Dividir los porcentajes ya redondeados daría 4,7
    y contradiría a los propios números de la frase: un cliente que divida
    lo que está leyendo tiene que obtener lo mismo que dice el texto."""
    lectura = pagina_ai.locator("#sovCard .aiv-lectura").inner_text()

    assert "4,4 veces más" in lectura
    assert "4,7" not in lectura
    assert "1 de cada 351" in lectura and "1 de cada 1.543" in lectura
    assert "890 búsquedas al mes" in lectura


def test_los_porcentajes_usan_coma_decimal(pagina_ai):
    """Mismo sistema de puntuación que el separador de miles que el
    dashboard ya usaba: "0.28%" al lado de "312.810" mezclaba dos."""
    legend = pagina_ai.locator("#sovCard .sov-legend").first.inner_text()
    assert "0,28%" in legend
    assert "0.28%" not in legend


# ── navegación: sidebar de dos secciones ─────────────────────────────────

def test_arranca_en_social_listening_con_el_otro_panel_oculto(pagina):
    assert pagina.locator("#panel-social").is_visible()
    assert not pagina.locator("#panel-ai").is_visible()
    assert pagina.locator("#b1").is_visible()
    assert not pagina.locator("#b11").is_visible()


def test_cambiar_de_seccion_muestra_solo_esa_seccion(pagina):
    pagina.locator('.nav-sec[data-panel="panel-ai"]').click()
    assert pagina.locator("#panel-ai").is_visible()
    assert not pagina.locator("#panel-social").is_visible()
    assert pagina.locator("#b11").is_visible()

    pagina.locator('.nav-sec[data-panel="panel-social"]').click()
    assert pagina.locator("#panel-social").is_visible()
    assert not pagina.locator("#panel-ai").is_visible()


def test_los_charts_sobreviven_al_ida_y_vuelta_entre_secciones(pagina):
    """Chart.js mide el contenedor al construirse: un canvas que pasó por
    display:none puede quedarse en 0px si nadie lo redimensiona."""
    pagina.wait_for_timeout(120)   # que se asiente lo que dejó el test anterior
    ancho_antes = pagina.locator("#chSentiment").evaluate("c => c.getBoundingClientRect().width")
    pagina.locator('.nav-sec[data-panel="panel-ai"]').click()
    pagina.locator('.nav-sec[data-panel="panel-social"]').click()
    pagina.wait_for_timeout(120)
    ancho_despues = pagina.locator("#chSentiment").evaluate("c => c.getBoundingClientRect().width")

    assert ancho_antes > 0
    assert abs(ancho_despues - ancho_antes) < 2


def test_un_ancla_a_otra_seccion_activa_esa_seccion_sola(pagina):
    """Los enlaces de referencia cruzada en prosa apuntan a bloques que
    viven en otro panel: sin activar el panel primero, el ancla no
    llegaría a ningún lado (display:none no se puede scrollear)."""
    pagina.evaluate("() => { document.querySelector('.nav-items[data-for=\\'panel-ai\\'] a[href=\\'#b11\\']').click(); }")
    pagina.wait_for_timeout(120)
    assert pagina.locator("#panel-ai").is_visible()
    assert pagina.locator("#b11").is_visible()
    pagina.locator('.nav-sec[data-panel="panel-social"]').click()


def test_ver_todo_en_una_sola_pagina_muestra_los_tres_paneles(pagina):
    """Es la contrapartida honesta de ocultar: Ctrl+F y la impresión no
    encuentran lo que está en display:none."""
    pagina.check("#chkAllView")
    pagina.wait_for_timeout(80)
    assert pagina.locator("#panel-social").is_visible()
    assert pagina.locator("#panel-ai").is_visible()

    pagina.uncheck("#chkAllView")
    pagina.wait_for_timeout(80)
    assert not pagina.locator("#panel-ai").is_visible()


def test_ningun_bloque_queda_fuera_de_los_tres_paneles(pagina):
    """Una <section id> que se quede fuera de un .panel sería invisible en
    cuanto se oculte otro panel: nadie la volvería a ver."""
    huerfanas = pagina.evaluate(
        "() => Array.from(document.querySelectorAll('section[id]'))"
        "        .filter(s => !s.closest('.panel')).map(s => s.id)"
    )
    assert huerfanas == []


def test_sin_scroll_horizontal_en_escritorio_y_en_movil(pagina):
    """Los cinco anchos que el proyecto verifica: 1440 y 1288 con el riel
    en flujo, 1287 y 1040 con el sidebar como cajón, y 390 de móvil.
    Reusa la pestaña del módulo (Playwright sync no permite anidar dos
    `sync_playwright()` a la vez) y devuelve el viewport al terminar."""
    original = pagina.viewport_size
    try:
        for ancho in (1440, 1288, 1287, 1040, 390):
            pagina.set_viewport_size({"width": ancho, "height": 900})
            pagina.wait_for_timeout(150)
            medido = pagina.evaluate("() => document.documentElement.scrollWidth")
            assert medido <= ancho, f"scroll horizontal del body a {ancho}px: {medido}"
    finally:
        pagina.set_viewport_size(original)
