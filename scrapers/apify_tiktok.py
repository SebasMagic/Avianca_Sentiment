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
        text = item.get("text", "") or item.get("description", "") or ""
        author_meta = item.get("authorMeta", {}) or {}

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "tiktok",
            "source_url": item.get("webVideoUrl", item.get("id", "")),
            "text": text,
            "author": author_meta.get("name", None),
            "published_at": item.get("createTimeISO") or None,
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
