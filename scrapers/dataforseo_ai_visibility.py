"""
DataForSEO AI Optimization / LLM Mentions — cuánto y cómo mencionan los
modelos de IA a la marca, qué fuentes citan al hablar de ella, y ejemplos
reales de pregunta+respuesta ya indexados.

Tres endpoints, todos POST .../v3/ai_optimization/llm_mentions/{fn}/live,
verificados contra la API real (2026-08-22):

  - target_metrics       — UNA marca (target=[{"domain": ...}]). Devuelve
                            aggregated_metrics.total (mentions,
                            ai_search_volume) y aggregated_metrics.
                            sources_domain (qué dominios citan los modelos
                            al hablar de esta marca — el hallazgo real:
                            para avianca.com, www.latamairlines.com
                            aparece entre las fuentes, y viceversa).
                            Costo real: $0,101 por marca (tarifa base
                            $0,1 + $0,001 por la única fila agregada que
                            devuelve).
  - multi_target_metrics — VARIAS marcas en un solo request
                            (targets=[{"key": nombre, "target": [...]},
                            ...]) — mismos campos que target_metrics, pero
                            por marca en `items[]`, más un total combinado.
                            Ojo con el formato: cada entrada de `targets`
                            necesita "key" (el nombre con el que se
                            identifica en items[]) además de "target" — sin
                            "key" la API responde 40501 "Field 'key' is
                            required" (verificado). Costo real: $0,102 para
                            2 marcas en un solo request — más barato que
                            dos llamadas de target_metrics separadas, y da
                            la comparación de una vez (scrape_comparison()).
  - search_mentions       — ejemplos reales de pregunta+respuesta que ya
                            mencionan la marca (hoy: Google AI Overview,
                            el único `platform` con datos para
                            location_code=2170/es — verificado). Trae el
                            texto completo de la respuesta y sus fuentes.
                            Costo real: $0,1 base + $0,001 por fila; con
                            `limit=config.LIMIT_AI_SEARCH_MENTINOS` (5)
                            queda en ~$0,105 por marca en vez de los $0,2
                            que costó explorar con el límite default (100).

`platform` (chat_gpt) para top_mentioned_brands/domains/pages/historical
solo tiene datos para location_code=2840/language_code=en (verificado:
2170/es devuelve 40501 "Invalid Field: 'location_code'" con
platform=chat_gpt) — no sirve para Colombia en español, así que esos
cuatro endpoints se exploraron pero NO se incorporaron a la captura
regular: top_mentioned_brands con una keyword de categoría en inglés
devolvió datos de comparación de aerolíneas contaminados de nombres de
CIUDADES DESTINO (São Paulo, Santiago, Quito como "brand_entities_title"),
no una comparación limpia de marcas — el equivalente en español
(config.AI_VISIBILITY_CATEGORY_PROMPTS) se responde mejor con prompts
propios al modelo (ver scrapers/dataforseo_ai_prompts.py) que con este
endpoint. top_mentioned_domains/top_pages son, para un target de dominio
propio, prácticamente el mismo dato que aggregated_metrics.sources_domain
que ya trae target_metrics — capturarlos aparte no habría agregado nada
nuevo por otros ~$0,10-0,13 cada uno.
"""
import uuid
from base64 import b64encode
from datetime import datetime, timezone

import requests

from config import (
    BRANDS, DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, LANGUAGE_CODE,
    LIMIT_AI_SEARCH_MENTIONS, LOCATION_CODE,
)

BASE_URL = "https://api.dataforseo.com/v3/ai_optimization/llm_mentions"


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def _post(fn: str, payload: dict) -> dict | None:
    """
    POST a un endpoint de llm_mentions. Devuelve tasks[0] entero (con su
    propio status_code/result), o None si la respuesta no tiene ni
    siquiera esa forma mínima — nunca lanza por un error de la API, para
    que un endpoint que falle no tumbe el resto de la captura.
    """
    response = requests.post(
        f"{BASE_URL}/{fn}/live", headers=_get_headers(), json=[payload], timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    try:
        return data["tasks"][0]
    except (KeyError, IndexError, TypeError):
        print(f"[DataForSEO AI Visibility] {fn}: respuesta sin tasks")
        return None


def _domain_root(domain: str) -> str:
    """"www.avianca.com" -> "avianca.com" — para comparar contra
    brand["domains"], que ya trae ambas variantes, basta con probar las
    dos formas (con y sin "www."); esta función solo cubre el caso común
    de un solo subdominio "www." al frente, no un dominio_root genérico."""
    return domain[4:] if domain.lower().startswith("www.") else domain


def _classify_source_domain(cited_domain: str, own_brand_name: str) -> tuple[bool, bool]:
    """
    (is_own_domain, is_competitor_domain) de `cited_domain` para la marca
    `own_brand_name`. "Propio" si está en brand["domains"] (con o sin
    "www."); "competidor" si está en el `domains` de CUALQUIER OTRA marca
    de config.BRANDS — así una marca nueva en BRANDS queda cubierta por
    esta función sin tocarla.
    """
    candidates = {cited_domain.lower(), _domain_root(cited_domain).lower()}
    own_domains = {d.lower() for d in BRANDS[own_brand_name]["domains"]}
    if candidates & own_domains:
        return True, False

    for other_name, other_brand in BRANDS.items():
        if other_name == own_brand_name:
            continue
        other_domains = {d.lower() for d in other_brand["domains"]}
        if candidates & other_domains:
            return False, True
    return False, False


def _metrics_row(brand_name: str, domain: str, aggregated: dict,
                  source_endpoint: str, captured_at: str, raw: dict) -> dict:
    total = aggregated.get("total") or {}
    platform_list = aggregated.get("platform") or []
    platform = platform_list[0]["key"] if platform_list else "google"
    return {
        "brand": brand_name,
        "captured_at": captured_at,
        "domain": domain,
        "platform": platform,
        "mentions": total.get("mentions", 0),
        "ai_search_volume": total.get("ai_search_volume", 0),
        "source_endpoint": source_endpoint,
        "raw": raw,
    }


def _source_rows(brand_name: str, aggregated: dict, source_endpoint: str,
                  captured_at: str) -> list[dict]:
    rows = []
    for s in aggregated.get("sources_domain") or []:
        cited = s.get("key")
        if not cited:
            continue
        is_own, is_competitor = _classify_source_domain(cited, brand_name)
        rows.append({
            "brand": brand_name,
            "captured_at": captured_at,
            "cited_domain": cited,
            "mentions": s.get("mentions", 0),
            "ai_search_volume": s.get("ai_search_volume", 0),
            "is_own_domain": is_own,
            "is_competitor_domain": is_competitor,
            "source_endpoint": source_endpoint,
        })
    return rows


def scrape(brand: dict, since: str | None = None) -> dict:
    """
    Captura de UNA marca: métricas agregadas + fuentes citadas
    (target_metrics) más ejemplos reales de Q&A (search_mentions).

    `since` no se usa — estos endpoints no filtran por fecha del lado del
    servidor y no tiene sentido un filtro del lado del cliente sobre un
    agregado (a diferencia de una lista de menciones con su propia fecha
    de publicación); se acepta el parámetro solo para que este scraper
    tenga la misma firma que el resto (main.py los llama todos igual).

    Reutiliza brand["review_domain"] como dominio raíz — ya es el dominio
    canónico verificado de la marca (mismo campo que usa
    scrapers/dataforseo_reviews.py para Trustpilot); no hace falta una
    clave nueva en el perfil para lo mismo.

    Devuelve {"brand_metrics": [...], "brand_sources": [...],
    "search_examples": [...]} — listos para store.db.insert_ai_brand_metrics
    / insert_ai_brand_sources / insert_ai_search_mention_examples. Un
    endpoint que falla deja su lista vacía sin tumbar los otros dos.
    """
    domain = brand.get("review_domain")
    if not domain:
        print(f"[DataForSEO AI Visibility] {brand.get('name')} no tiene "
              f"review_domain configurado — se omite")
        return {"brand_metrics": [], "brand_sources": [], "search_examples": []}

    captured_at = datetime.now(timezone.utc).isoformat()
    brand_name = brand["name"]

    brand_metrics: list[dict] = []
    brand_sources: list[dict] = []
    search_examples: list[dict] = []

    task = _post("target_metrics", {
        "target": [{"domain": domain}],
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
    })
    if task and task.get("status_code") == 20000:
        try:
            result = task["result"][0]
            aggregated = result["aggregated_metrics"]
        except (KeyError, IndexError, TypeError):
            aggregated = None
        if aggregated:
            brand_metrics.append(_metrics_row(
                brand_name, domain, aggregated, "target_metrics", captured_at, result))
            brand_sources.extend(
                _source_rows(brand_name, aggregated, "target_metrics", captured_at))
    else:
        print(f"[DataForSEO AI Visibility] target_metrics falló para {brand_name}: "
              f"{task.get('status_message') if task else 'sin respuesta'}")

    task = _post("search_mentions", {
        "target": [{"domain": domain}],
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
        "limit": LIMIT_AI_SEARCH_MENTIONS,
        "order_by": ["ai_search_volume,desc"],
    })
    if task and task.get("status_code") == 20000:
        try:
            items = task["result"][0]["items"] or []
        except (KeyError, IndexError, TypeError):
            items = []
        for item in items:
            sources = item.get("sources") or []
            top_source = sources[0] if sources else {}
            search_examples.append({
                "brand": brand_name,
                "captured_at": captured_at,
                "platform": item.get("model_name") or item.get("platform"),
                "question": item.get("question"),
                "answer": item.get("answer"),
                "ai_search_volume": item.get("ai_search_volume"),
                "top_source_domain": top_source.get("domain"),
                "top_source_url": top_source.get("url"),
                "raw": item,
            })
    else:
        print(f"[DataForSEO AI Visibility] search_mentions falló para {brand_name}: "
              f"{task.get('status_message') if task else 'sin respuesta'}")

    print(f"[DataForSEO AI Visibility] {brand_name}: "
          f"{len(brand_metrics)} métrica(s), {len(brand_sources)} fuente(s), "
          f"{len(search_examples)} ejemplo(s) de Q&A")

    return {
        "brand_metrics": brand_metrics,
        "brand_sources": brand_sources,
        "search_examples": search_examples,
    }


def scrape_comparison(brand_names: list[str] | None = None) -> dict:
    """
    Comparación entre TODAS las marcas de `brand_names` (default:
    config.BRANDS completo) en un solo request de multi_target_metrics —
    endpoint 2 del encargo. No encaja en la firma `scrape(brand, ...)` de
    un solo perfil porque su razón de ser es comparar varias marcas a la
    vez; se invoca por separado (main.py: --comparar-marcas-ia), una vez,
    no en el loop por marca.

    Devuelve la misma forma que scrape() (sin "search_examples", que ese
    endpoint no trae) pero con filas de LAS DOS marcas juntas, etiquetadas
    source_endpoint="multi_target_metrics" — para que ai_brand_metrics
    pueda distinguir "esto salió de mirar la marca sola" de "esto salió
    de una comparación directa", aunque ambos números deberían coincidir
    (misma marca, mismo agregado) salvo variación entre corridas.
    """
    names = brand_names if brand_names is not None else list(BRANDS)
    targets = []
    for name in names:
        domain = BRANDS[name].get("review_domain")
        if domain:
            targets.append({"key": name, "target": [{"domain": domain}]})

    if not targets:
        print("[DataForSEO AI Visibility] scrape_comparison: ninguna marca con "
              "review_domain configurado")
        return {"brand_metrics": [], "brand_sources": []}

    captured_at = datetime.now(timezone.utc).isoformat()
    brand_metrics: list[dict] = []
    brand_sources: list[dict] = []

    task = _post("multi_target_metrics", {
        "targets": targets,
        "location_code": LOCATION_CODE,
        "language_code": LANGUAGE_CODE,
    })
    if not task or task.get("status_code") != 20000:
        print(f"[DataForSEO AI Visibility] multi_target_metrics falló: "
              f"{task.get('status_message') if task else 'sin respuesta'}")
        return {"brand_metrics": [], "brand_sources": []}

    try:
        items = task["result"][0]["items"] or []
    except (KeyError, IndexError, TypeError):
        items = []

    for item in items:
        brand_name = item.get("key")
        if brand_name not in BRANDS:
            continue
        domain = BRANDS[brand_name].get("review_domain", "")
        brand_metrics.append(_metrics_row(
            brand_name, domain, item, "multi_target_metrics", captured_at, item))
        brand_sources.extend(
            _source_rows(brand_name, item, "multi_target_metrics", captured_at))

    print(f"[DataForSEO AI Visibility] comparación: {len(brand_metrics)} marca(s), "
          f"{len(brand_sources)} fuente(s) citadas en total")

    return {"brand_metrics": brand_metrics, "brand_sources": brand_sources}
