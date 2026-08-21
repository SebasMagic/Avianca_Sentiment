"""
Backfill retroactivo del filtro de relevancia de hashtag (Tarea 3 —
corrección de relevancia social) — aplica pipeline/relevance.is_relevant()
a las menciones de TikTok que YA están en la DB, guardadas antes de que
ese filtro existiera (ver pipeline/relevance.py: antes, todo el contenido
social pasaba directo).

No gasta API: opera sobre `text`/`author` ya guardados en `mentions`, sin
volver a golpear Apify. No borra ninguna fila — marca exclusion_reason
(store/db.set_exclusion_reason) en las que ya no pasan la regla nueva, y
dashboard/aggregate.py las omite de todas las agregaciones sin que la fila
deje de existir (igual que ya se hace con las menciones fuera de la
ventana de reporte).

Idempotente y reversible por construcción: cada corrida recalcula
is_relevant() desde cero sobre CADA mención de TikTok (sin importar su
exclusion_reason actual) y escribe el resultado tal cual — una fila que
hoy está excluida pero que la regla (ya corregida/recalibrada) volvería a
aceptar, se REINCLUYE automáticamente (exclusion_reason vuelve a NULL) en
la misma corrida, no hace falta un modo aparte para "deshacer".
"""
import collections

from config import get_brand
from pipeline.relevance import is_relevant
from store import db


def run(conn, brand: str | None = None) -> dict:
    """
    `brand`: acota el backfill a una sola marca (recomendado — así una
    corrida de LATAM no recalcula también las de Avianca); None recorre
    todas las marcas presentes en la DB.
    """
    mentions = db.all_mentions(conn, brand=brand)
    tiktok_mentions = [m for m in mentions if m["platform"] == "tiktok"]

    if not tiktok_mentions:
        print("[SocialRelevanceBackfill] sin menciones de TikTok que evaluar")
        return {"evaluated": 0, "excluded": 0, "restored": 0, "reasons": {}}

    # Perfil de marca resuelto una vez por nombre de marca presente en el
    # lote — nunca un default congelado, is_relevant() necesita el perfil
    # correcto de CADA mención (ver docstring de is_relevant).
    brand_cache: dict[str, dict] = {}

    excluded = 0
    restored = 0
    reasons = collections.Counter()

    for m in tiktok_mentions:
        brand_name = m.get("brand")
        if brand_name not in brand_cache:
            brand_cache[brand_name] = get_brand(brand_name)

        ok, razon = is_relevant(m, brand_cache[brand_name])
        was_excluded = bool(m.get("exclusion_reason"))

        if ok:
            if was_excluded:
                db.set_exclusion_reason(conn, m["id"], None)
                restored += 1
        else:
            if m.get("exclusion_reason") != razon:
                db.set_exclusion_reason(conn, m["id"], razon)
            excluded += 1
            reasons[razon] += 1

    print(
        f"[SocialRelevanceBackfill] {len(tiktok_mentions)} evaluadas — "
        f"{excluded} excluidas, {restored} reincluidas — razones: {dict(reasons)}"
    )
    return {
        "evaluated": len(tiktok_mentions),
        "excluded": excluded,
        "restored": restored,
        "reasons": dict(reasons),
    }
