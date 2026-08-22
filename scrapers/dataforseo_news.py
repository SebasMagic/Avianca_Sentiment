"""
DataForSEO Google News scraper — cobertura de prensa sobre la marca.

Endpoint verificado contra la API real (2026-08-21/22):

    POST https://api.dataforseo.com/v3/serp/google/news/live/advanced
    [{"keyword": brand["keyword"], "location_code": ..., "language_code": ...,
      "depth": config.LIMIT_NEWS}]

Costo real observado: $0,004 por consulta (depth=20).

La forma real de la respuesta NO es una lista plana de items con
domain/title/snippet/url/timestamp — eso describe el ítem individual,
pero tasks[0].result[0].items mezcla dos formas distintas (verificado
con datos reales, no con la documentación):

  - un bloque type="top_stories": UN solo elemento de nivel superior
    cuyo propio campo "items" trae varias noticias anidadas (source,
    domain, title, date, timestamp, url — SIN "snippet").
  - elementos type="news_search": ya planos, con domain/title/url/
    snippet/timestamp/time_published.

_flatten_items() aplana ambas formas a una lista uniforme antes de
mapear al schema unificado. Un depth=20 típico trae ~20 noticias
repartidas entre ambos tipos (verificado para "Avianca": 9 en
top_stories + 11 sueltas), no 20 elementos de nivel superior — y el
bloque top_stories y los sueltos a veces repiten el mismo artículo (1
duplicado de 20 en la corrida verificada), por eso se dedup por URL acá.

Sin filtro de relevancia en este módulo — lo aplica pipeline/
relevance.py después (is_relevant(), rama "prensa"), igual que el resto
de plataformas. Sin clasificación tampoco: sentiment/emotion/is_complaint
quedan sin poblar, a la espera de pipeline/classify_pending.py.
"""
import uuid
from base64 import b64encode
from datetime import datetime, timezone

import requests

from config import (
    COUNTRY_CODE, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
    LANGUAGE_CODE, LIMIT_NEWS, LOCATION_CODE,
)


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def _flatten_items(items: list[dict]) -> list[dict]:
    """
    Aplana tasks[0].result[0].items: los bloques type="top_stories"
    esconden las noticias reales en su propio campo "items" (una lista);
    el resto de tipos observados (type="news_search") ya son planos y
    traen "domain" directamente, se toman tal cual. Cualquier tipo
    desconocido que no traiga ni "items" ni "domain" se ignora en
    silencio en vez de reventar — el schema de SERP de Google News no
    está documentado de forma estable y un bloque nuevo no debe tumbar
    el scraper completo.
    """
    flat = []
    for entry in items or []:
        nested = entry.get("items")
        if isinstance(nested, list):
            flat.extend(nested)
        elif entry.get("domain"):
            flat.append(entry)
    return flat


def _parse_timestamp(raw: str | None) -> str | None:
    """
    "2026-08-21 11:14:08 +00:00" -> ISO 8601. Formato verificado contra
    datos reales de ambos tipos de ítem (top_stories y news_search) —
    los dos usan el mismo formato de timestamp. None si falta o no
    parsea — nunca se inventa una fecha (regla dura, ver
    pipeline/normalizer.py: sin fecha, date_confidence='unknown').
    """
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z").isoformat()
    except ValueError:
        return None


def scrape(brand: dict, since: str | None = None) -> list[dict]:
    """
    Consulta Google News (vía DataForSEO) por brand["keyword"] y retorna
    menciones de prensa sobre `brand` en el schema unificado
    (platform="prensa"). `since` (YYYY-MM-DD) filtra del lado del
    cliente — el endpoint no acepta un rango de fechas; None no filtra
    nada, igual que el resto de scrapers cuando se les pide un backfill
    sin fecha explícita.
    """
    payload = [{
        "keyword": brand["keyword"],
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
        "depth": LIMIT_NEWS,
    }]

    response = requests.post(
        "https://api.dataforseo.com/v3/serp/google/news/live/advanced",
        headers=_get_headers(),
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    try:
        raw_items = data["tasks"][0]["result"][0]["items"]
    except (KeyError, IndexError, TypeError):
        print("[DataForSEO News] Sin items en la respuesta")
        return []

    fetched_at = datetime.now(timezone.utc).isoformat()
    seen_urls: set[str] = set()
    results = []

    for item in _flatten_items(raw_items):
        url = item.get("url") or ""
        if url and url in seen_urls:
            continue  # top_stories y news_search a veces repiten el mismo artículo
        if url:
            seen_urls.add(url)

        published_at = _parse_timestamp(item.get("timestamp"))
        if since and published_at and published_at[:10] < since:
            continue

        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        text = f"{title}. {snippet}" if snippet else title
        if not text.strip():
            continue

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "prensa",
            "source_url": url or None,
            "text": text,
            "author": (item.get("domain") or "").lower() or None,
            "published_at": published_at,
            "country": COUNTRY_CODE,
            "likes": 0,
            "shares": 0,
            "comments_count": 0,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[DataForSEO News] {len(results)} notas de prensa extraídas para {brand['keyword']}")
    return results
