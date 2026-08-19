"""
Apify Instagram scraper.
Fase 1: obtiene posts recientes de @avianca.
Fase 2: extrae comentarios de esos posts — son usuarios reales quejándose o elogiando.
Sentiment se procesa después en sentiment_engine.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import APIFY_API_TOKEN, APIFY_INSTAGRAM_ACTOR, LIMIT_INSTAGRAM, BRAND_KEYWORD, INSTAGRAM_PROFILES

YEAR_FILTER = "2026"


def scrape() -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)
    fetched_at = datetime.now(timezone.utc).isoformat()

    profiles = INSTAGRAM_PROFILES.get(BRAND_KEYWORD, INSTAGRAM_PROFILES["Avianca"])

    # ── FASE 1: obtener URLs de posts recientes ──────────────────
    print(f"[Instagram] Fase 1 — obteniendo posts de {BRAND_KEYWORD}...")
    posts_run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": profiles,
        "resultsType": "posts",
        "resultsLimit": 20,
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
    comments_run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": post_urls[:15],
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

        # Filtrar por año
        timestamp = item.get("timestamp", "")
        if timestamp and YEAR_FILTER not in str(timestamp)[:4]:
            continue

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "instagram",
            "source_url": item.get("url", post_urls[0] if post_urls else ""),
            "text": text,
            "author": item.get("ownerUsername", None),
            "published_at": timestamp or fetched_at,
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
