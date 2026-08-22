"""
Agregaciones del bloque de visibilidad de marca en IA y del bloque de
share of voice en búsqueda. Mismo criterio que dashboard/aggregate.py
(sin HTML, sin red) pero sobre las tablas de store/db.py propias de este
bloque (ai_brand_metrics, ai_brand_sources, ai_prompt_responses,
ai_prompt_brand_mentions, ai_search_mention_examples,
search_share_of_voice) — nunca sobre `mentions`.

Honestidad ante datos no capturados (mismo criterio que el resto del
reporte, ver dashboard/aggregate.py): cada sub-bloque trae su propio
`captured_at` (o None) y el payload nunca rellena con 0 lo que
simplemente no se ha corrido todavía — el dashboard debe poder decir
"esto no se ha capturado aún" en vez de mostrar un cero engañoso.

"La captura más reciente" se agrupa por `run_id`, no por igualdad de
`captured_at` — ver store.db.latest_completed_run: dentro de UNA corrida
de pipeline.ai_visibility.run(), cada prompt propio
(scrapers/dataforseo_ai_prompts.py) recibe su propio timestamp (son
varias llamadas HTTP secuenciales), así que solo `run_id` es constante
para toda la corrida. ai_brand_metrics/ai_brand_sources son la única
excepción: ahí sí se agrupa por igualdad de `captured_at` porque
scrapers/dataforseo_ai_visibility.py calcula ESE timestamp una sola vez
por llamada a scrape() y lo reutiliza en ambas tablas — más simple que
otro cruce con `runs`, y funciona igual de bien si el dato más reciente
vino de --visibilidad-ia (source_endpoint="target_metrics") o de
--comparar-marcas-ia (source_endpoint="multi_target_metrics"): cualquiera
de las dos sirve como "el número vigente".
"""
from config import get_brand
from store import db

# Cuántas fuentes citadas y cuántos ejemplos de Q&A se muestran — el
# resto queda en la DB, auditable, pero el dashboard no necesita listar
# los diez si el hallazgo ya se ve con los primeros.
TOP_SOURCES = 8
MAX_QUOTES = 6

# Excerpt de una respuesta larga — se corta para que las tarjetas de
# "qué dicen textualmente" no dominen la página; el texto COMPLETO sigue
# en la DB (raw / response_text), esto es solo lo que se muestra.
EXCERPT_LEN = 380


def _excerpt(text: str | None) -> str:
    text = (text or "").strip()
    if len(text) <= EXCERPT_LEN:
        return text
    return text[:EXCERPT_LEN].rsplit(" ", 1)[0] + "…"


def _dominant_label(pos, neg, neu) -> str | None:
    """
    Mismo criterio de desempate que dashboard.aggregate._dominant_label
    (negative > neutral > positive) — se reimplementa acá en vez de
    importarla porque es una función privada de ese módulo (nombre con
    guion bajo) y este archivo tiene su propia fuente de filas (join de
    ai_prompt_brand_mentions, no `mentions`). None si no hay sentimiento
    que mostrar (marca que no aparece en el texto, nunca se clasificó).
    """
    if pos is None and neg is None and neu is None:
        return None
    candidatos = [("negative", neg or 0), ("neutral", neu or 0), ("positive", pos or 0)]
    return max(candidatos, key=lambda par: par[1])[0]


def _latest_metrics_and_sources(conn, brand_name: str) -> dict | None:
    metrics_rows = db.ai_brand_metrics_for_brand(conn, brand_name)
    if not metrics_rows:
        return None
    latest = metrics_rows[0]  # ya viene ordenado DESC por captured_at

    sources_rows = db.ai_brand_sources_for_brand(conn, brand_name)
    sources = [s for s in sources_rows if s["captured_at"] == latest["captured_at"]]
    sources.sort(key=lambda s: s["mentions"], reverse=True)

    return {
        "brand": brand_name,
        "mentions": latest["mentions"],
        "ai_search_volume": latest["ai_search_volume"],
        "domain": latest["domain"],
        "captured_at": latest["captured_at"],
        "source_endpoint": latest["source_endpoint"],
        "sources": [{
            "domain": s["cited_domain"],
            "mentions": s["mentions"],
            "ai_search_volume": s["ai_search_volume"],
            "is_own_domain": bool(s["is_own_domain"]),
            "is_competitor_domain": bool(s["is_competitor_domain"]),
        } for s in sources[:TOP_SOURCES]],
    }


def _prompt_entry(row: dict) -> dict:
    return {
        "prompt": row["prompt"],
        "model": row["model"],
        "appears": bool(row["appears"]),
        "position": row["position"],
        "sentiment": _dominant_label(
            row["sentiment_positive"], row["sentiment_negative"], row["sentiment_neutral"]),
        "excerpt": _excerpt(row["response_text"]),
        "captured_at": row["captured_at"],
    }


def build_ai_visibility_payload(conn, brand: str) -> dict:
    """
    `brand`: nombre de marca (ver config.BRANDS) — a diferencia de
    dashboard.aggregate.build_payload, este bloque SIEMPRE es de una
    marca (no existe una "vista combinada" para visibilidad en IA: cada
    fila ya es una métrica por marca, no una mención que se pueda
    mezclar). La comparación contra competidores vive DENTRO del payload
    de la marca propia (own vs. competitors), no como un payload aparte.
    """
    profile = get_brand(brand)
    competitor_names = profile.get("competitors") or []

    own = _latest_metrics_and_sources(conn, brand)
    competitors = []
    missing_competitors = []
    for name in competitor_names:
        data = _latest_metrics_and_sources(conn, name)
        if data:
            competitors.append(data)
        else:
            missing_competitors.append(name)

    ai_run = db.latest_completed_run(conn, brand, "ai_visibility")
    run_id = ai_run["id"] if ai_run else None

    prompt_rows = db.ai_prompt_responses_for_brand(conn, brand)
    if run_id:
        prompt_rows = [r for r in prompt_rows if r["run_id"] == run_id]
    category_prompts = [_prompt_entry(r) for r in prompt_rows if r["prompt_scope"] == "category"]
    brand_prompts = [_prompt_entry(r) for r in prompt_rows if r["prompt_scope"] == "brand"]

    search_rows = db.ai_search_mention_examples_for_brand(conn, brand)
    if run_id:
        search_rows = [r for r in search_rows if r["run_id"] == run_id]
    search_examples = [{
        "question": r["question"],
        "answer": _excerpt(r["answer"]),
        "platform": r["platform"],
        "ai_search_volume": r["ai_search_volume"],
        "source_domain": r["top_source_domain"],
        "source_url": r["top_source_url"],
        "captured_at": r["captured_at"],
    } for r in search_rows[:MAX_QUOTES]]

    return {
        "brand": brand,
        "own": own,
        "competitors": competitors,
        "missing_competitors": missing_competitors,
        "category_prompts": category_prompts,
        "brand_prompts": brand_prompts,
        "search_examples": search_examples,
        "has_metrics": own is not None,
        "has_prompts": bool(category_prompts or brand_prompts),
        "has_search_examples": bool(search_examples),
        "captured_at": ai_run["finished_at"] if ai_run else (own["captured_at"] if own else None),
    }


def build_share_of_voice_payload(conn, brand: str) -> dict:
    """
    Volumen de búsqueda por intención (problema vs. comercial) y motor
    (google_ads vs. ai_search) para `brand`, de la captura más reciente
    (mismo run_id que agrupa el resto de este bloque — ver docstring del
    módulo).
    """
    run = db.latest_completed_run(conn, brand, "ai_visibility")
    rows = db.search_share_of_voice_for_brand(conn, brand)
    if run:
        rows = [r for r in rows if r["run_id"] == run["id"]]
    else:
        rows = []

    by_engine: dict[str, dict] = {}
    for r in rows:
        engine = by_engine.setdefault(r["engine"], {
            "problema": 0, "comercial": 0, "keywords": [],
        })
        vol = r["search_volume"] or 0
        if r["intent"] in ("problema", "comercial"):
            engine[r["intent"]] += vol
        engine["keywords"].append({
            "keyword": r["keyword"], "intent": r["intent"], "search_volume": r["search_volume"],
        })

    for engine_data in by_engine.values():
        engine_data["keywords"].sort(key=lambda k: k["search_volume"] or 0, reverse=True)
        total = engine_data["problema"] + engine_data["comercial"]
        engine_data["problem_pct"] = (
            round(engine_data["problema"] / total * 100, 1) if total else None
        )

    return {
        "brand": brand,
        "by_engine": by_engine,
        "has_data": bool(rows),
        "captured_at": run["finished_at"] if run else None,
    }
