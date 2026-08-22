"""
DataForSEO Content Analysis scraper.
Retorna menciones web/blogs/Reddit con sentiment nativo incluido.
Excluye dominios oficiales de la marca y filtra por fecha (`since`).

Fuera del pipeline activo (Cambio 1, retiro del canal web): este módulo se
conserva pero no está en la lista SCRAPERS de main.py — mismo tratamiento
que scrapers/apify_twitter.py. Decisión del usuario, con evidencia:

  - 71 menciones web entre Avianca y LATAM producen solo 2 quejas reales.
  - Desde el diagnóstico inicial, esta capa es ~95% agregadores de vuelos
    (Kayak, Despegar, Skyscanner, etc. — ver config.BLACKLIST_DOMAIN_ROOTS,
    que ya los descarta, y aun así lo que queda no es mejor).
  - Una revisión manual de la muestra que SÍ pasa el filtro encontró: un
    casino online ("vbet latam"), una página de registro de eventos
    (luma.com), un directorio de empresas (emis.com), spam SEO
    (diskgrafica.com, con "latam sigla" repetido) y granjas de teléfonos
    falsos suplantando el call center (id.carousell.com).

No es conversación de aerolíneas. Las menciones web YA guardadas en la DB
no se borran — quedan marcadas con exclusion_reason (ver
pipeline/web_channel_retirement.py) y las agregaciones del dashboard las
omiten, igual que se hizo con la irrelevancia social de TikTok. El módulo
no se borra por si en el futuro se justifica retomarlo con un filtro más
estricto que el de config.BLACKLIST_DOMAIN_ROOTS.
"""
import uuid
import requests
from base64 import b64encode
from datetime import datetime, timezone
from config import (
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
    LANGUAGE_CODE, LIMIT_DATAFORSEO, BACKFILL_SINCE,
)


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json"
    }


def scrape(brand: dict, since: str | None = None) -> list[dict]:
    """
    Consulta DataForSEO y retorna menciones de usuarios sobre `brand`.
    `since` es una fecha YYYY-MM-DD; si es None usa BACKFILL_SINCE.
    """
    payload = [{
        "keyword": brand["keyword"],
        "language_code": LANGUAGE_CODE,
        "limit": LIMIT_DATAFORSEO,
        "date_from": since or BACKFILL_SINCE,
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
    domains = brand["domains"]

    for item in items:
        domain = item.get("domain", "") or ""

        # Saltar páginas oficiales de la marca
        if domain.lower() in domains:
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

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "web",
            "source_url": item.get("url", ""),
            "text": text,
            "author": domain or None,
            "published_at": item.get("date_published") or None,
            "country": "CO",
            "likes": 0,
            "shares": 0,
            "comments_count": 0,
            "sentiment_positive": pos,
            "sentiment_negative": neg,
            "sentiment_neutral": conn.get("neutral", 1.0) or 1.0,
            "emotion": dominant_emotion,
            "is_complaint": False,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[DataForSEO] {len(results)} menciones extraídas (dominios oficiales excluidos)")
    return results
