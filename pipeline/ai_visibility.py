"""
Orquesta la captura de visibilidad de marca en IA para UNA marca: métricas
+ fuentes citadas + ejemplos de Q&A (scrapers/dataforseo_ai_visibility.py),
prompts propios al modelo (scrapers/dataforseo_ai_prompts.py) y share of
voice en búsqueda (scrapers/dataforseo_share_of_voice.py) — y la
comparación directa entre marcas (multi_target_metrics), que corre aparte
porque no es de una sola marca.

Mismo patrón que pipeline/classify_pending.py: abre y cierra su propia
`runs` (mode="ai_visibility" / "ai_visibility_comparison") para que quede
trazado cuándo se corrió esto y con qué resultado, igual que cualquier
otra corrida del pipeline.
"""
from config import BRANDS
from scrapers import dataforseo_ai_prompts, dataforseo_ai_visibility, dataforseo_share_of_voice
from store import db


def run(conn, brand: dict) -> dict:
    """
    Corre las tres capturas de UNA marca y las persiste. Cada una es
    independiente: si una falla (scraper atrapa el error y devuelve listas
    vacías, ver docstrings de cada módulo), las otras dos igual se
    guardan — no hay una sola API que pueda tumbar toda la corrida.
    """
    run_id = db.start_run(conn, "ai_visibility", None, brand=brand["name"])

    visibilidad = dataforseo_ai_visibility.scrape(brand)
    n_metrics = db.insert_ai_brand_metrics(conn, visibilidad["brand_metrics"], run_id)
    n_sources = db.insert_ai_brand_sources(conn, visibilidad["brand_sources"], run_id)
    n_examples = db.insert_ai_search_mention_examples(conn, visibilidad["search_examples"], run_id)

    prompt_results = dataforseo_ai_prompts.scrape(brand)
    n_responses = 0
    for item in prompt_results:
        db.insert_ai_prompt_response(conn, item["response"], item["mentions"], run_id)
        n_responses += 1

    sov_rows = dataforseo_share_of_voice.scrape(brand)
    n_sov = db.insert_search_share_of_voice(conn, sov_rows, run_id)

    resumen = {
        "brand_metrics": n_metrics,
        "brand_sources": n_sources,
        "search_examples": n_examples,
        "prompt_responses": n_responses,
        "share_of_voice": n_sov,
    }
    db.finish_run(
        conn, run_id, raw_count=sum(resumen.values()), filtered_count=0,
        inserted_count=sum(resumen.values()), duplicate_count=0,
        notes=f"visibilidad-ia: {resumen}",
    )
    print(f"[AIVisibility] {brand['name']}: {resumen}")
    return resumen


def run_comparison(conn) -> dict:
    """
    Comparación directa entre TODAS las marcas de config.BRANDS
    (multi_target_metrics, un solo request) — no toma `brand` porque por
    definición compara varias a la vez. Se corre una sola vez, no una por
    marca (ver main.py: --comparar-marcas-ia).
    """
    run_id = db.start_run(conn, "ai_visibility_comparison", None, brand="ALL")

    comparacion = dataforseo_ai_visibility.scrape_comparison(list(BRANDS))
    n_metrics = db.insert_ai_brand_metrics(conn, comparacion["brand_metrics"], run_id)
    n_sources = db.insert_ai_brand_sources(conn, comparacion["brand_sources"], run_id)

    resumen = {"brand_metrics": n_metrics, "brand_sources": n_sources}
    db.finish_run(
        conn, run_id, raw_count=sum(resumen.values()), filtered_count=0,
        inserted_count=sum(resumen.values()), duplicate_count=0,
        notes=f"comparacion-ia: {resumen}",
    )
    print(f"[AIVisibility] comparación: {resumen}")
    return resumen
