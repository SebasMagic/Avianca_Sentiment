"""
Share of voice en búsqueda — cuánto se busca la marca en clave de PROBLEMA
("demanda", "reclamo", "queja") frente a clave COMERCIAL ("vuelos",
"ofertas", "check in"), en dos motores distintos:

  - google_ads — keywords_data/google_ads/search_volume/live: volumen de
    búsqueda REAL en Google (Google Ads Keyword Planner). Endpoint
    verificado (2026-08-22): 20 keywords (10 por marca: 5 de problema +
    5 comerciales) en un solo request costaron $0,09 en total.
  - ai_search  — ai_optimization/ai_keyword_data/keywords_search_volume/
    live: volumen estimado de uso en herramientas de IA (mismo concepto
    que ai_search_volume del resto de endpoints de ai_optimization, pero
    aplicado a estas keywords de intención). Verificado: 3 keywords
    costaron $0,0103 ($0,0034-0,0035 por keyword aprox.).

Las keywords salen de config.get_share_of_voice_keywords(brand["name"]) —
"{keyword de la marca} {término}", nunca hardcodeadas acá; una marca
nueva en config.BRANDS hereda el mismo set de términos automáticamente.

Ambos endpoints reciben la lista COMPLETA (problema + comercial) de una
marca en un solo request cada uno — dos llamadas por marca en total, no
diez, para no pagar la tarifa base de cada endpoint por cada keyword
suelta.
"""
from base64 import b64encode
from datetime import datetime, timezone

import requests

from config import (
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, LANGUAGE_CODE, LOCATION_CODE,
    get_share_of_voice_keywords,
)

GOOGLE_ADS_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
AI_KEYWORD_URL = (
    "https://api.dataforseo.com/v3/ai_optimization/ai_keyword_data/"
    "keywords_search_volume/live"
)


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def _post(url: str, payload: dict) -> dict | None:
    response = requests.post(url, headers=_get_headers(), json=[payload], timeout=60)
    response.raise_for_status()
    data = response.json()
    try:
        return data["tasks"][0]
    except (KeyError, IndexError, TypeError):
        print(f"[DataForSEO Share of Voice] {url}: respuesta sin tasks")
        return None


def _intent_by_keyword(keyword_specs: list[dict]) -> dict[str, str]:
    return {spec["keyword"]: spec["intent"] for spec in keyword_specs}


def scrape(brand: dict, since: str | None = None) -> list[dict]:
    """
    Volumen de búsqueda (Google Ads y AI search) para el set de keywords
    de intención de `brand`. `since` no se usa (mismo motivo que el resto
    de módulos de este bloque — un agregado de volumen mensual no es una
    lista fechada de menciones); se acepta solo por uniformidad de firma.

    Devuelve una lista de filas listas para
    store.db.insert_search_share_of_voice — dos por keyword (una por
    motor) cuando ambos endpoints responden bien; una sola si alguno
    falla (el otro no se descarta por eso).
    """
    keyword_specs = get_share_of_voice_keywords(brand["name"])
    intent_by_kw = _intent_by_keyword(keyword_specs)
    keywords = list(intent_by_kw)
    captured_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    task = _post(GOOGLE_ADS_URL, {
        "keywords": keywords, "location_code": LOCATION_CODE, "language_code": LANGUAGE_CODE,
    })
    if task and task.get("status_code") == 20000:
        for item in task.get("result") or []:
            kw = item.get("keyword")
            if kw not in intent_by_kw:
                continue
            rows.append({
                "brand": brand["name"], "captured_at": captured_at, "keyword": kw,
                "intent": intent_by_kw[kw], "engine": "google_ads",
                "search_volume": item.get("search_volume"), "raw": item,
            })
    else:
        print(f"[DataForSEO Share of Voice] google_ads falló para {brand['name']}: "
              f"{task.get('status_message') if task else 'sin respuesta'}")

    task = _post(AI_KEYWORD_URL, {
        "keywords": keywords, "location_code": LOCATION_CODE, "language_code": LANGUAGE_CODE,
    })
    if task and task.get("status_code") == 20000:
        try:
            items = task["result"][0]["items"] or []
        except (KeyError, IndexError, TypeError):
            items = []
        for item in items:
            kw = item.get("keyword")
            if kw not in intent_by_kw:
                continue
            rows.append({
                "brand": brand["name"], "captured_at": captured_at, "keyword": kw,
                "intent": intent_by_kw[kw], "engine": "ai_search",
                "search_volume": item.get("ai_search_volume"), "raw": item,
            })
    else:
        print(f"[DataForSEO Share of Voice] ai_search falló para {brand['name']}: "
              f"{task.get('status_message') if task else 'sin respuesta'}")

    print(f"[DataForSEO Share of Voice] {len(rows)} filas para {brand['name']} "
          f"({len(keywords)} keywords x hasta 2 motores)")
    return rows
