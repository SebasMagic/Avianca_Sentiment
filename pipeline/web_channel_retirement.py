"""
Retiro del canal web (Cambio 1) — marca TODAS las menciones platform='web'
ya en la DB (de la marca que se le pase, o de todas) como excluidas de las
agregaciones del dashboard, usando exclusion_reason. Nunca borra filas.

No gasta ninguna API: opera sobre `platform`/`exclusion_reason`, ya
guardados, sin volver a golpear DataForSEO ni ninguna otra fuente.

Motivo (decisión del usuario, ver scrapers/dataforseo_scraper.py y main.py
para el detalle completo): 71 menciones web entre las dos marcas producen
solo 2 quejas reales. Desde el diagnóstico inicial esta capa es ~95%
agregadores de vuelos; una revisión manual de la muestra encontró además
un casino online, una página de registro de eventos, un directorio de
empresas, spam SEO y granjas de teléfonos falsos suplantando el call
center — no es conversación de aerolíneas.

A diferencia de pipeline/social_relevance_backfill.py, esto NO es una regla
recalculable caso por caso (no hay un is_relevant() que evalúe cada texto):
es una decisión de política — el canal completo se retira. Por eso este
módulo marca TODO lo que sea platform='web' sin evaluar el contenido de
cada fila, a diferencia del filtro de hashtag de TikTok. Reversible por
diseño de la misma forma que el resto: es una columna, no una fila
borrada — reincluir el canal es volver a poner exclusion_reason en NULL
para esas filas (set_exclusion_reason(conn, id, None) fila por fila, o un
script equivalente a este que invierta la marca).
"""
from config import WEB_CHANNEL_RETIREMENT_REASON
from store import db


def run(conn, brand: str | None = None) -> dict:
    """
    `brand`: acota el retiro a una sola marca (recomendado, para poder
    correrlo y verificarlo marca por marca); None lo aplica a todas las
    marcas presentes en la DB.

    Idempotente: una mención web ya marcada con esta razón no se vuelve a
    tocar (no cuenta como "recién marcada" en el resultado), así que
    correrlo dos veces no hace nada distinto la segunda vez.
    """
    mentions = db.all_mentions(conn, brand=brand)
    web_mentions = [m for m in mentions if m["platform"] == "web"]

    marked = 0
    already_marked = 0
    for m in web_mentions:
        if m.get("exclusion_reason") == WEB_CHANNEL_RETIREMENT_REASON:
            already_marked += 1
            continue
        db.set_exclusion_reason(conn, m["id"], WEB_CHANNEL_RETIREMENT_REASON)
        marked += 1

    print(
        f"[WebChannelRetirement] {len(web_mentions)} menciones web evaluadas — "
        f"{marked} marcadas ahora, {already_marked} ya estaban marcadas"
    )
    return {
        "evaluated": len(web_mentions),
        "marked": marked,
        "already_marked": already_marked,
    }
