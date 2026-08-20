"""
Backfill retroactivo de `source_account` (cuenta de Instagram que publicó
el post) para comentarios que YA están en la DB — Tarea 4 (comparación
igualada): sin esto no se puede desagregar LATAM por cuenta global vs.
local, porque los comentarios de LATAM se scrapearon ANTES de que Task 1
existiera.

Mismo patrón que pipeline/instagram_reach_backfill.py: UNA sola llamada de
Fase 1 (resultsType='posts') sobre los `postUrl` únicos que ya viven en el
`raw` guardado — nunca vuelve a pedir comentarios (Fase 2, ya pagados).

Acotado por marca (a diferencia de instagram_reach_backfill.run(), que no
lo está — hallazgo de la corrida anterior, ver .superpowers/latam-backfill.md
§5): sin `brand`, un backfill de LATAM re-pagaría también los posts de
Avianca. Y acotado además a filas con source_account IS NULL: si se corre
dos veces, la segunda vez no hay nada que pedir — no se re-paga por datos
que ya se verificaron.
"""
from scrapers.apify_instagram import fetch_post_reach
from store import db


def _unique_post_urls(mentions: list[dict]) -> list[str]:
    urls = set()
    for m in mentions:
        if m["platform"] != "instagram" or m.get("source_account"):
            continue
        raw = m.get("raw") or {}
        post_url = raw.get("postUrl")
        if post_url:
            urls.add(post_url)
    return sorted(urls)


def run(conn, brand: str | None = None, fetch_fn=fetch_post_reach) -> dict:
    """
    fetch_fn es inyectable para tests (evita golpear Apify); por defecto
    es la llamada real de scrapers.apify_instagram.fetch_post_reach.
    """
    mentions = db.all_mentions(conn, brand=brand)
    post_urls = _unique_post_urls(mentions)

    if not post_urls:
        print("[SourceAccountBackfill] nada pendiente (sin postUrl o ya poblado)")
        return {"posts_requested": 0, "posts_found": 0,
                "mentions_enriched": 0, "mentions_without_owner": 0}

    print(f"[SourceAccountBackfill] pidiendo Fase 1 de {len(post_urls)} posts...")
    reach_map = fetch_fn(post_urls)

    enriched = 0
    without_owner = 0
    for m in mentions:
        if m["platform"] != "instagram" or m.get("source_account"):
            continue
        raw = m.get("raw") or {}
        post_url = raw.get("postUrl")
        if not post_url:
            continue
        reach = reach_map.get(post_url)
        owner = reach.get("owner_username") if reach else None
        if owner is None:
            without_owner += 1
            continue
        db.update_source_account(conn, m["id"], owner)
        enriched += 1

    print(f"[SourceAccountBackfill] {enriched} menciones enriquecidas con cuenta de origen, "
          f"{without_owner} sin dato (post ya no disponible o sin ownerUsername)")
    return {
        "posts_requested": len(post_urls),
        "posts_found": len(reach_map),
        "mentions_enriched": enriched,
        "mentions_without_owner": without_owner,
    }
