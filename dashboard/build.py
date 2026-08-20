"""
Genera el dashboard HTML autocontenido.

Un solo archivo: Chart.js inline y la data inyectada como JSON.
Abre con doble clic, funciona sin internet, se manda por correo.

Multi-marca: build(brand=...) / `python -m dashboard.build --brand LATAM`
genera el dashboard de una marca — título, encabezado, logo (o wordmark) y
color de acento salen de config.BRANDS, nunca hardcodeados aquí. Sin
--brand, se conserva el comportamiento y el nombre de archivo históricos
(Avianca, avianca_dashboard_<fecha>.html) para no romper nada existente.
"""
import base64
import colorsys
import json
from datetime import datetime, timezone
from pathlib import Path

from config import DEFAULT_BRAND, get_brand
from dashboard.aggregate import build_payload
from store import db

TEMPLATE = Path(__file__).parent / "template.html"
VENDOR = Path(__file__).parent / "vendor" / "chart.umd.min.js"
LOGO = Path(__file__).parent.parent / "Logo_wordmark_Avianca_(Colombia).png"
PROJECT_ROOT = Path(__file__).parent.parent

DATA_MARKER = "__DASHBOARD_DATA__"
VENDOR_MARKER = "__CHARTJS__"
# Legado: marcador de src puntual para el logo de Avianca. Se conserva tal
# cual (no lo usa la plantilla real, que ya pasó a BRAND_LOGO_MARKER) para
# no romper plantillas o pruebas que sigan inyectando el logo de esta forma
# directa.
LOGO_MARKER = "__AVIANCA_LOGO__"

# ── Marcadores conscientes de marca — sustituidos desde el perfil
# (config.BRANDS), nunca hardcodeados por marca en la plantilla. ──────────
BRAND_TITLE_MARKER = "__BRAND_TITLE__"
BRAND_NAME_MARKER = "__BRAND_NAME__"
BRAND_LOGO_MARKER = "__BRAND_LOGO_HTML__"
BRAND_COLOR_MARKER = "__BRAND_COLOR__"
BRAND_INK_MARKER = "__BRAND_INK__"
BRAND_DIM_MARKER = "__BRAND_DIM__"
BRAND_MID_MARKER = "__BRAND_MID__"
# "web" colisiona con el color de marca cuando la marca es azul (LATAM) —
# ver _platform_web_color() y la nota en template.html junto a PLT_COLOR.
BRAND_WEB_COLOR_MARKER = "__BRAND_WEB_COLOR__"


# ── Color: --brand-ink/--brand-dim/--brand-mid salen SIEMPRE del `color`
# del perfil, nunca hardcodeados por marca — con una sola excepción
# explícita y documentada (_KNOWN_BRAND_INK) para no mover ni un pixel del
# rojo de Avianca, ya calibrado a mano en producción. ─────────────────────

_MIN_TEXT_CONTRAST = 4.5  # WCAG AA para texto normal — criterio del skill dataviz

# Avianca: --brand-ink ya calibrado a mano en producción (contraste 5.9:1
# sobre blanco — ver comentario original en template.html). Se preserva
# tal cual, en vez de recalcularlo con _derive_ink(), para que el
# dashboard de Avianca no pierda ni un pixel de su look actual al pasar
# por esta derivación genérica (Tarea 3: "Avianca conserva exactamente el
# look actual"). Cualquier otro color — LATAM incluida — cae en el cálculo
# genérico de _derive_ink().
_KNOWN_BRAND_INK = {"#F62839": "#C81030"}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _relative_luminance(hex_color: str) -> float:
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _derive_ink(color: str) -> str:
    """
    Variante de `color` segura como texto sobre blanco (WCAG AA, >= 4.5:1
    — el criterio del skill dataviz), para usar como --brand-ink cuando
    --brand es demasiado claro para servir de texto (caso Avianca:
    #F62839 da solo 3.98:1 — ver _contrast_ratio). Si `color` YA cumple el
    umbral tal cual (caso LATAM: #1B0088 da ~15:1, un azul lo bastante
    oscuro para ser su propio texto), se devuelve sin tocar — no toda
    marca necesita una variante oscurecida.

    Oscurece en HSL, en pasos pequeños de luminosidad, manteniendo tono y
    saturación — la misma idea que el --brand-ink de Avianca (una versión
    más oscura de la misma familia de rojo), aplicada de forma genérica
    para que una marca futura no necesite tocar este archivo a mano.
    """
    if color in _KNOWN_BRAND_INK:
        return _KNOWN_BRAND_INK[color]
    if _contrast_ratio(color, "#FFFFFF") >= _MIN_TEXT_CONTRAST:
        return color
    r, g, b = _hex_to_rgb(color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    ink = color
    while _contrast_ratio(ink, "#FFFFFF") < _MIN_TEXT_CONTRAST and l > 0:
        l = max(0.0, l - 0.02)
        nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
        ink = "#{:02X}{:02X}{:02X}".format(round(nr * 255), round(ng * 255), round(nb * 255))
    return ink


def _brand_dim(color: str) -> str:
    """rgba(...) del color de marca a alpha .07 — fondo tenue de chrome de
    marca (fondo del KPI héroe, .drv-pill, etc). Alpha fija, calcada de la
    que ya se usaba a mano para el rojo de Avianca."""
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r},{g},{b},.07)"


def _brand_mid(color: str) -> str:
    """rgba(...) del color de marca a alpha .45 — bordes/foco de chrome de
    marca. Misma alpha que ya se usaba a mano para Avianca."""
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r},{g},{b},.45)"


# Azul "web" de los gráficos (PLT_COLOR.web en template.html) — estable
# entre marcas por defecto: es un identificador de PLATAFORMA, no de
# marca, y debe leerse igual en cualquier reporte. Verificado con el
# validador del skill dataviz (scripts/validate_palette.js) que este azul
# (#2A78D6, hue ~212°) y el azul de marca de LATAM (#1B0088, hue ~252°,
# ~40° de separación) dan ΔE 24–28 entre sí — muy por encima del piso
# CVD (8) y del piso de visión normal (15): NO son la misma señal, ni para
# un lector con daltonismo ni sin él. Los reemplazos alternativos
# probados (grises/ocres cercanos al dorado de tendencia) fallaban el piso
# de croma del validador o colisionaban con --gold (línea de tendencia,
# hue ~43°) — así que "web" se deja intacto para AMBAS marcas.
_WEB_PLATFORM_COLOR = "#2A78D6"


def _brand_logo_html(profile: dict) -> str:
    """
    Bloque HTML del logo del encabezado, a partir del perfil de marca.

    Con archivo de logo (Avianca): <img> con el PNG embebido como data URI
    base64 — igual que Chart.js, para que el archivo siga autocontenido.

    Sin archivo de logo (LATAM: profile["logo"] es None, o el archivo no
    existe): wordmark tipográfico — nombre de marca en negrita, con una
    barra de acento en el color de marca al lado. Deliberadamente NO un
    cuadro vacío ni un placeholder: es una lockup compuesta a propósito
    (ver .brand-wordmark/.wm-mark en template.html), con una forma
    (barra rectangular) distinta del punto circular que usan los swatches
    de plataforma, para que tampoco se lea como un swatch más.
    """
    name = profile["name"]
    logo_rel = profile.get("logo")
    if logo_rel:
        logo_path = PROJECT_ROOT / logo_rel
        if logo_path.exists():
            b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
            return f'<img class="brand-logo" src="data:image/png;base64,{b64}" alt="{name}">'
    return (
        f'<span class="brand-wordmark" role="img" aria-label="{name}">'
        f'<span class="wm-mark"></span>{name}</span>'
    )


def render(payload: dict, template_path: str = str(TEMPLATE),
           brand_name: str = DEFAULT_BRAND) -> str:
    html = Path(template_path).read_text(encoding="utf-8")
    profile = get_brand(brand_name)  # falla temprano y claro si la marca no existe

    # Escapar </script> — un comentario que lo contenga rompería el HTML.
    data = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    html = html.replace(DATA_MARKER, data)

    if VENDOR_MARKER in html:
        html = html.replace(VENDOR_MARKER, VENDOR.read_text(encoding="utf-8"))

    # Legado — ver docstring de LOGO_MARKER arriba.
    if LOGO_MARKER in html and LOGO.exists():
        logo_b64 = base64.b64encode(LOGO.read_bytes()).decode("ascii")
        html = html.replace(LOGO_MARKER, f"data:image/png;base64,{logo_b64}")

    if BRAND_LOGO_MARKER in html:
        html = html.replace(BRAND_LOGO_MARKER, _brand_logo_html(profile))

    if BRAND_TITLE_MARKER in html:
        html = html.replace(BRAND_TITLE_MARKER, f"{profile['name']} — Social Listening")

    if BRAND_NAME_MARKER in html:
        html = html.replace(BRAND_NAME_MARKER, profile["name"])

    if BRAND_COLOR_MARKER in html:
        html = html.replace(BRAND_COLOR_MARKER, profile["color"])

    if BRAND_INK_MARKER in html:
        html = html.replace(BRAND_INK_MARKER, _derive_ink(profile["color"]))

    if BRAND_DIM_MARKER in html:
        html = html.replace(BRAND_DIM_MARKER, _brand_dim(profile["color"]))

    if BRAND_MID_MARKER in html:
        html = html.replace(BRAND_MID_MARKER, _brand_mid(profile["color"]))

    if BRAND_WEB_COLOR_MARKER in html:
        html = html.replace(BRAND_WEB_COLOR_MARKER, _WEB_PLATFORM_COLOR)

    return html


def build(db_path: str | None = None, out_dir: str = "dashboard", conn=None,
          brand: str = DEFAULT_BRAND) -> str:
    get_brand(brand)  # falla temprano y claro si la marca no existe en config.BRANDS

    own_conn = conn is None
    if own_conn:
        conn = db.connect(db_path) if db_path else db.connect()

    try:
        payload = build_payload(conn, brand=brand)
    finally:
        if own_conn:
            conn.close()

    html = render(payload, brand_name=brand)

    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Slug de archivo = nombre de marca en minúsculas — para Avianca esto
    # reproduce exactamente "avianca_dashboard_<fecha>.html", el nombre
    # histórico, sin necesidad de un caso especial.
    slug = brand.lower()
    out_path = Path(out_dir) / f"{slug}_dashboard_{fecha}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"[Dashboard] {out_path}  ({payload['kpis']['total']} menciones · marca={brand})")
    return str(out_path)


DEPLOY_DIR = Path(__file__).parent.parent / "deploy"


def stage_for_deploy(html_path: str) -> str:
    """
    Copia el dashboard a deploy/index.html para publicarlo en Vercel.

    Brand-agnóstico a propósito: recibe la ruta del HTML ya generado (de
    cualquier marca) y lo copia tal cual — así --deploy puede stagear el
    dashboard de Avianca o el de LATAM sin ninguna rama especial aquí.

    El index.html queda fuera de git a propósito: contiene los nombres de
    usuario y los textos de cientos de personas reales. La configuración de
    deploy/ (vercel.json, robots.txt) sí se versiona; el contenido no.
    """
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    destino = DEPLOY_DIR / "index.html"
    destino.write_text(Path(html_path).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[Deploy] listo en {destino} — publicar con:  vercel deploy --prod deploy")
    return str(destino)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Genera el dashboard HTML de una marca.")
    parser.add_argument("--brand", default=DEFAULT_BRAND,
                         help=f"Marca a reportar (default: {DEFAULT_BRAND}). Ver config.BRANDS.")
    parser.add_argument("--deploy", action="store_true",
                         help="Además, stagea el HTML generado en deploy/index.html.")
    args = parser.parse_args()

    generado = build(brand=args.brand)
    if args.deploy:
        stage_for_deploy(generado)
