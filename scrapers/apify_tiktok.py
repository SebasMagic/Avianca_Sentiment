"""
Apify TikTok scraper.
Extrae videos que mencionan Avianca en Colombia.
Sentiment se procesa después en pipeline/classifier.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import APIFY_API_TOKEN, APIFY_TIKTOK_ACTOR, BRAND_KEYWORD, LIMIT_TIKTOK


def scrape(since: str | None = None) -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "hashtags": [BRAND_KEYWORD.lower(), f"{BRAND_KEYWORD.lower()}colombia"],
        "resultsPerPage": LIMIT_TIKTOK,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }
    if since:
        run_input["oldestPostDate"] = since

    print(f"[TikTok] Iniciando actor {APIFY_TIKTOK_ACTOR}...")
    run = client.actor(APIFY_TIKTOK_ACTOR).call(run_input=run_input)

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []

    for item in items:
        timestamp = item.get("createTimeISO")

        # FILTRO DEL LADO DEL CLIENTE — verificado con datos reales de
        # producción: clockworks/tiktok-scraper IGNORA "oldestPostDate"
        # (arriba, run_input). Un backfill pedido con --since 2026-04-19
        # devolvió igual 24 videos de 2023, 2024 y 2025. El parámetro del
        # actor se deja puesto como defensa en profundidad, pero no basta
        # por sí solo — este filtro es el que realmente descarta lo
        # anterior a `since`, igual que ya hace apify_instagram.py con sus
        # comentarios. NO "simplificar" quitando este bloque: sin él, el
        # backfill vuelve a colar contenido fuera del rango pedido.
        if since and timestamp and str(timestamp)[:10] < since:
            continue

        text = item.get("text", "") or item.get("description", "") or ""
        author_meta = item.get("authorMeta", {}) or {}

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "tiktok",
            "source_url": item.get("webVideoUrl", item.get("id", "")),
            "text": text,
            "author": author_meta.get("name", None),
            "published_at": timestamp or None,
            "country": "CO",
            "likes": item.get("diggCount", 0) or 0,
            "shares": item.get("shareCount", 0) or 0,
            "comments_count": item.get("commentCount", 0) or 0,
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "is_complaint": False,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[TikTok] {len(results)} videos extraídos")
    return results
