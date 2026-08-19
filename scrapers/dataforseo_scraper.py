"""
DataForSEO Content Analysis scraper.
Retorna menciones web/blogs/Reddit con sentiment nativo incluido.
Excluye dominios oficiales de Avianca y filtra por año actual.
"""
import uuid
import requests
from base64 import b64encode
from datetime import datetime, timezone
from config import (
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
    BRAND_KEYWORD, LANGUAGE_CODE, LIMIT_DATAFORSEO,
    BRAND_DOMAINS as BRAND_DOMAINS_MAP,
)

BRAND_DOMAINS = BRAND_DOMAINS_MAP.get(BRAND_KEYWORD, set())

DATE_FROM = "2026-01-01"


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json"
    }


def scrape() -> list[dict]:
    """
    Consulta DataForSEO y retorna menciones de usuarios (excluye páginas oficiales).
    El sentiment viene nativo del API.
    """
    payload = [{
        "keyword": BRAND_KEYWORD,
        "language_code": LANGUAGE_CODE,
        "limit": LIMIT_DATAFORSEO,
        "date_from": DATE_FROM,
    }]

    response = requests.post(
        "https://api.dataforseo.com/v3/content_analysis/search/live",
        headers=_get_headers(),
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    data = response.json()

    results = []
    try:
        items = data["tasks"][0]["result"][0]["items"]
    except (KeyError, IndexError, TypeError):
        print("[DataForSEO] No items in response")
        return []

    fetched_at = datetime.now(timezone.utc).isoformat()

    for item in items:
        domain = item.get("domain", "") or ""

        # Saltar páginas oficiales de la marca
        if domain.lower() in BRAND_DOMAINS:
            continue

        conn = item.get("connotation_types", {}) or {}
        sent_conns = item.get("sentiment_connotations", {}) or {}

        emotion_map = {
            "anger":     sent_conns.get("anger",     0) or 0,
            "happiness": sent_conns.get("happiness", 0) or 0,
            "love":      sent_conns.get("love",      0) or 0,
            "sadness":   sent_conns.get("sadness",   0) or 0,
        }
        dominant_emotion = max(emotion_map, key=emotion_map.get)
        if emotion_map[dominant_emotion] == 0:
            dominant_emotion = "neutral"

        content_info = item.get("content_info", {}) or {}
        text = content_info.get("snippet", "") or item.get("title", "") or ""

        neg = conn.get("negative", 0.0) or 0.0
        pos = conn.get("positive", 0.0) or 0.0

        # Queja real = sentiment negativo dominante en fuente independiente
        is_complaint = neg > 0.4 and neg > pos

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "web",
            "source_url": item.get("url", ""),
            "text": text,
            "author": domain or None,
            "published_at": item.get("date_published", fetched_at),
            "country": "CO",
            "likes": 0,
            "shares": 0,
            "comments_count": 0,
            "sentiment_positive": pos,
            "sentiment_negative": neg,
            "sentiment_neutral": conn.get("neutral", 1.0) or 1.0,
            "emotion": dominant_emotion,
            "is_complaint": is_complaint,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[DataForSEO] {len(results)} menciones extraídas (dominios oficiales excluidos)")
    return results
