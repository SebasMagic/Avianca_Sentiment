"""
Apify Instagram scraper.
Fase 1: obtiene posts recientes de @avianca.
Fase 2: extrae comentarios de esos posts — son usuarios reales quejándose o elogiando.
Sentiment se procesa después en pipeline/classifier.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import (
    APIFY_API_TOKEN, APIFY_INSTAGRAM_ACTOR, LIMIT_INSTAGRAM, BRAND_KEYWORD,
    INSTAGRAM_PROFILES, INSTAGRAM_POSTS_LIMIT,
)


def scrape(since: str | None = None) -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)
    fetched_at = datetime.now(timezone.utc).isoformat()

    profiles = INSTAGRAM_PROFILES.get(BRAND_KEYWORD, INSTAGRAM_PROFILES["Avianca"])

    # ── FASE 1: obtener URLs de posts recientes ──────────────────
    print(f"[Instagram] Fase 1 — obteniendo posts de {BRAND_KEYWORD}...")
    posts_run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": profiles,
        "resultsType": "posts",
        "resultsLimit": INSTAGRAM_POSTS_LIMIT,
    })
    posts = list(client.dataset(posts_run["defaultDatasetId"]).iterate_items())

    post_urls = []
    for p in posts:
        if "error" in p:
            continue
        url = p.get("url", "")
        shortcode = p.get("shortCode", "")
        if url.startswith("http"):
            post_urls.append(url)
        elif shortcode:
            post_urls.append(f"https://www.instagram.com/p/{shortcode}/")

    if not post_urls:
        print("[Instagram] Sin posts para extraer comentarios")
        return []

    print(f"[Instagram] {len(post_urls)} posts encontrados — Fase 2: extrayendo comentarios...")

    # ── FASE 2: extraer comentarios de esos posts ────────────────
    # post_urls ya viene acotado por INSTAGRAM_POSTS_LIMIT en Fase 1 (no
    # se trunca de nuevo aquí a 15).
    comments_run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": post_urls,
        "resultsType": "comments",
        "resultsLimit": LIMIT_INSTAGRAM,
    })
    items = list(client.dataset(comments_run["defaultDatasetId"]).iterate_items())

    results = []
    for item in items:
        if "error" in item:
            continue

        text = item.get("text", "") or item.get("ownerUsername", "") or ""
        if not text.strip():
            continue

        timestamp = item.get("timestamp", "")
        if since and timestamp and str(timestamp)[:10] < since:
            continue

        # DEFECTO CORREGIDO (Task 8): la Fase 2 pide comentarios de VARIOS
        # posts a la vez (directUrls=post_urls), así que un mismo dataset
        # mezcla comentarios de todos ellos. El actor de Apify no expone
        # "url" en los ítems de tipo comentario (esa clave solo existe en
        # los ítems de tipo post de la Fase 1); confiar en item.get("url")
        # con fallback a post_urls[0] hacía que el 100% de los comentarios
        # cayeran a la URL del primer post, sin importar de cuál vinieran
        # realmente — eso fusionó personas distintas en el dedup por
        # fingerprint (mitigado en Task 4 incluyendo el autor, pero la
        # URL degenerada seguía siendo la causa raíz).
        #
        # Fix: usar "postUrl" (el post real al que pertenece el
        # comentario, según el schema del actor) con fallback a "url" por
        # compatibilidad, y sólo caer a post_urls[0] si el ítem no trae
        # ninguno de los dos. Sobre esa base, anexar "#comment-{id}" con
        # el id propio del comentario para que cada comentario tenga una
        # source_url distinta — sin esto, todos los comentarios de un
        # mismo post seguían colisionando entre sí. Si el ítem tampoco
        # trae "id", se cae al comportamiento anterior (source_url = URL
        # del post, compartida entre comentarios) en vez de inventar un
        # identificador falso.
        #
        # NO "simplificar" esto de vuelta a item.get("url", post_urls[0]):
        # eso fue el defecto original, verificado con datos reales de
        # Apify donde el 100% de 189 comentarios colisionaban en una sola
        # URL.
        post_url = item.get("postUrl") or item.get("url") or (post_urls[0] if post_urls else "")
        comment_id = item.get("id")
        source_url = f"{post_url}#comment-{comment_id}" if comment_id else post_url

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "instagram",
            "source_url": source_url,
            "text": text,
            "author": item.get("ownerUsername", None),
            "published_at": timestamp or None,
            "country": "CO",
            "likes": item.get("likesCount", 0) or 0,
            "shares": 0,
            "comments_count": 0,
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "is_complaint": False,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[Instagram] {len(results)} comentarios extraídos")
    return results
