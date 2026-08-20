"""
Backfill retroactivo del alcance (views) de los comentarios de Instagram ya
guardados en la DB — Tarea 2 del desglose de engagement.

Los comentarios de Instagram que ya están en data/avianca.db se scrapearon
con la Fase 1 vieja, que descartaba todo salvo la URL del post. Este comando
reconstruye el mapa {post_url: alcance} con UNA sola llamada de Fase 1 sobre
los `postUrl` únicos que ya viven en el `raw` guardado, y actualiza
views + reach_source de cada comentario que pertenezca a esos posts.

NO vuelve a pedir comentarios (Fase 2) — esos ya están pagados y en la DB;
solo se paga la Fase 1 de los posts que los originaron.

Idempotente en la escritura a DB: dado el mismo mapa de alcance, recalcula
y sobreescribe los mismos valores, nunca acumula. Repetir el comando sí
vuelve a gastar en la llamada real a Apify — no hay forma de evitarlo sin
persistir el resultado crudo de Fase 1 aparte, y no vale la pena para algo
que cuesta centavos y se corre una vez.
"""
from scrapers.apify_instagram import fetch_post_reach
from store import db


def _unique_post_urls(mentions: list[dict]) -> list[str]:
    urls = set()
    for m in mentions:
        if m["platform"] != "instagram":
            continue
        raw = m.get("raw") or {}
        post_url = raw.get("postUrl")
        if post_url:
            urls.add(post_url)
    return sorted(urls)


def run(conn, fetch_fn=fetch_post_reach) -> dict:
    """
    fetch_fn es inyectable para tests (evita golpear Apify); por defecto es
    la llamada real de scrapers.apify_instagram.fetch_post_reach.
    """
    mentions = db.all_mentions(conn)
    post_urls = _unique_post_urls(mentions)

    if not post_urls:
        print("[InstagramReach] sin postUrl en la DB — nada que enriquecer")
        return {"posts_requested": 0, "posts_found": 0,
                "comments_enriched": 0, "comments_without_views": 0}

    print(f"[InstagramReach] pidiendo Fase 1 de {len(post_urls)} posts...")
    reach_map = fetch_fn(post_urls)

    enriched = 0
    without_views = 0
    for m in mentions:
        if m["platform"] != "instagram":
            continue
        raw = m.get("raw") or {}
        post_url = raw.get("postUrl")
        if not post_url:
            continue
        reach = reach_map.get(post_url)
        views = reach.get("views") if reach else None
        if views is None:
            without_views += 1
            continue
        db.update_engagement(conn, m["id"], {"views": views, "reach_source": "post"})
        enriched += 1

    print(f"[InstagramReach] {enriched} comentarios enriquecidos con alcance de post, "
          f"{without_views} sin views (post de imagen o sin dato)")
    return {
        "posts_requested": len(post_urls),
        "posts_found": len(reach_map),
        "comments_enriched": enriched,
        "comments_without_views": without_views,
    }
