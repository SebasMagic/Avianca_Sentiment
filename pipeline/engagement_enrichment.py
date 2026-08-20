"""
Enriquecimiento retroactivo de engagement/alcance desde el `raw` ya guardado
en cada mención — sin llamar a ninguna API, sin gastar un centavo.

Diagnóstico (verificado sobre data/avianca.db, 1.261 filas):

  hoy `engagement = likes + shares + comments_count`. TikTok trae en su
  `raw` dos campos que nunca se extrajeron a columna — `collectCount`
  (saves) y `playCount` (views) — y esas views son, con frecuencia, un
  orden de magnitud mayor que el engagement reportado. Instagram trae
  `likesCount` del comentario, que ya se guardaba en `likes`, así que ahí
  esta pasada es sobre todo una re-derivación de consistencia.

Mapeo verificado contra items reales (no asumido):

  TikTok (item de video, cuando trae 'diggCount' — 85 de 174 filas):
    diggCount    -> likes
    commentCount -> comments_count
    shareCount   -> shares
    collectCount -> saves
    playCount    -> views, reach_source='propio'
                    (las views son del video mismo — no de un contenedor)

  Instagram (item de comentario, cuando trae 'likesCount' — 909 de 1056 filas):
    likesCount -> likes
    (shares, comments_count y saves NO se tocan aquí: un comentario no
    tiene shares ni saves propios — no es límite del actor, es qué ES un
    comentario. El alcance de Instagram, `views`, no vive en el raw de un
    comentario — lo trae la Fase 1 de scrapers/apify_instagram.py, ver
    pipeline/instagram_reach_backfill.py, Tarea 2.)

Filas sin el campo esperado en `raw` (el seed del Excel v1 guarda
`raw={"origen": "seed_excel_v1"}`; cualquier otra plataforma) quedan
intactas — NULL, no cero. No se inventa un valor para lo que no se midió.

Idempotente: recalcula desde el mismo `raw` cada vez, nunca acumula ni suma
sobre el valor anterior — correrlo N veces con el mismo raw da el mismo
resultado.
"""
from store import db


def _from_tiktok(raw: dict) -> dict | None:
    if "diggCount" not in raw:
        return None
    views = raw.get("playCount")
    return {
        "likes": raw.get("diggCount") or 0,
        "comments_count": raw.get("commentCount") or 0,
        "shares": raw.get("shareCount") or 0,
        "saves": raw.get("collectCount") or 0,
        "views": views if views is not None else None,
        "reach_source": "propio" if views is not None else None,
    }


def _from_instagram(raw: dict) -> dict | None:
    if "likesCount" not in raw:
        return None
    return {
        "likes": raw.get("likesCount") or 0,
    }


_MAPPERS = {
    "tiktok": _from_tiktok,
    "instagram": _from_instagram,
}


def run(conn, brand: str | None = None) -> dict:
    """
    `brand` es opcional: sin él, enriquece todas las marcas (comportamiento
    histórico); pasándolo (el nombre, p.ej. "LATAM"), lo acota a una sola.
    """
    mentions = db.all_mentions(conn, brand=brand)
    enriched = 0
    skipped = 0
    by_platform: dict[str, int] = {}

    for m in mentions:
        mapper = _MAPPERS.get(m["platform"])
        if mapper is None:
            skipped += 1
            continue
        fields = mapper(m.get("raw") or {})
        if not fields:
            skipped += 1
            continue
        db.update_engagement(conn, m["id"], fields)
        enriched += 1
        by_platform[m["platform"]] = by_platform.get(m["platform"], 0) + 1

    print(f"[Engagement] {enriched} filas enriquecidas desde raw, {skipped} sin raw completo")
    return {"enriched": enriched, "skipped": skipped, "by_platform": by_platform}
