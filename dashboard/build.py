"""
Genera el dashboard HTML autocontenido.

Un solo archivo: Chart.js inline y la data inyectada como JSON.
Abre con doble clic, funciona sin internet, se manda por correo.
"""
import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from dashboard.aggregate import build_payload
from store import db

TEMPLATE = Path(__file__).parent / "template.html"
VENDOR = Path(__file__).parent / "vendor" / "chart.umd.min.js"
LOGO = Path(__file__).parent.parent / "Logo_wordmark_Avianca_(Colombia).png"

DATA_MARKER = "__DASHBOARD_DATA__"
VENDOR_MARKER = "__CHARTJS__"
LOGO_MARKER = "__AVIANCA_LOGO__"


def render(payload: dict, template_path: str = str(TEMPLATE)) -> str:
    html = Path(template_path).read_text(encoding="utf-8")

    # Escapar </script> — un comentario que lo contenga rompería el HTML.
    data = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    html = html.replace(DATA_MARKER, data)

    if VENDOR_MARKER in html:
        html = html.replace(VENDOR_MARKER, VENDOR.read_text(encoding="utf-8"))

    if LOGO_MARKER in html and LOGO.exists():
        # Data URI base64 — el logo vive dentro del HTML, igual que Chart.js,
        # para que el archivo siga siendo autocontenido y funcione offline.
        logo_b64 = base64.b64encode(LOGO.read_bytes()).decode("ascii")
        html = html.replace(LOGO_MARKER, f"data:image/png;base64,{logo_b64}")

    return html


def build(db_path: str | None = None, out_dir: str = "dashboard", conn=None) -> str:
    own_conn = conn is None
    if own_conn:
        conn = db.connect(db_path) if db_path else db.connect()

    try:
        payload = build_payload(conn)
    finally:
        if own_conn:
            conn.close()

    html = render(payload)

    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = Path(out_dir) / f"avianca_dashboard_{fecha}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"[Dashboard] {out_path}  ({payload['kpis']['total']} menciones)")
    return str(out_path)


DEPLOY_DIR = Path(__file__).parent.parent / "deploy"


def stage_for_deploy(html_path: str) -> str:
    """
    Copia el dashboard a deploy/index.html para publicarlo en Vercel.

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
    import sys

    generado = build()
    if "--deploy" in sys.argv:
        stage_for_deploy(generado)
