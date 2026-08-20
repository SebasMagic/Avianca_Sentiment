"""
Apify Twitter/X scraper.
Extrae tweets del perfil oficial @avianca y @aviancacolombia.
Nota: el scraping de búsqueda en X requiere actor de pago en Apify.
      Usamos el perfil oficial como fuente de datos confiable.
Sentiment se procesa después en sentiment_engine.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import APIFY_API_TOKEN, APIFY_TWITTER_ACTOR, LIMIT_TWITTER


def scrape() -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "startUrls": [
            {"url": "https://twitter.com/avianca"},
        ],
        "maxItems": LIMIT_TWITTER,
    }

    print(f"[Twitter] Iniciando actor {APIFY_TWITTER_ACTOR}...")
    try:
        run = client.actor(APIFY_TWITTER_ACTOR).call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        print(f"[Twitter] Error llamando actor: {e}")
        return []

    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []

    for item in items:
        # Filtrar resultados demo/vacíos
        if "demo" in item or "noResults" in item:
            continue

        text = item.get("text", "") or item.get("full_text", "") or ""
        if not text.strip():
            continue

        author = item.get("author", {}) or {}

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "twitter",
            "source_url": item.get("url", ""),
            "text": text,
            "author": author.get("userName", item.get("userName", None)),
            "published_at": item.get("createdAt") or None,
            "country": "CO",
            "likes": item.get("likeCount", 0) or 0,
            "shares": item.get("retweetCount", 0) or 0,
            "comments_count": item.get("replyCount", 0) or 0,
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "is_complaint": False,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[Twitter] {len(results)} tweets extraídos")
    return results
