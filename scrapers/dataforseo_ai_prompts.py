"""
DataForSEO AI Optimization / ChatGPT LLM Responses — le hacemos a un
modelo real las preguntas que un cliente potencial le haría antes de
volar (config.get_ai_prompts, derivado del perfil de marca — nunca
hardcodeado por marca acá) y guardamos la respuesta completa.

Endpoint verificado contra la API real (2026-08-22):

    POST https://api.dataforseo.com/v3/ai_optimization/chat_gpt/llm_responses/live
    [{"user_prompt": ..., "model_name": "gpt-4o-mini", "max_output_tokens": 400}]

Costo real observado: $0,000763 por request (~$0,0006-0,0008, en línea
con la estimación del encargo). Modelo fijado en config.AI_VISIBILITY_MODEL
(gpt-4o-mini, el más barato de la lista con soporte completo — ver
ai_optimization/chat_gpt/llm_responses/models).

De cada respuesta se extrae, para la marca `brand` Y para cada uno de sus
competidores (brand["competitors"]) — así un prompt de categoría sin
nombrar a nadie ("¿cuál es la mejor aerolínea...?") deja comparación
completa desde UNA sola respuesta, sin pagar dos veces la misma pregunta:

  - appears:   si el nombre de esa marca aparece en el texto (por palabra
               completa, sin distinguir mayúsculas — _mentions_brand()).
  - position:  1 = la primera marca (de las que aparecen) mencionada en
               el texto, 2 = la segunda, etc. None si no aparece.
  - sentiment/emotion: solo para las marcas que SÍ aparecen — se
               reutiliza pipeline/classifier.classify_texts(), el mismo
               clasificador que ya usa el resto del pipeline (mismo
               contrato: puede devolver None si no logra clasificar, y
               ese None se guarda tal cual, nunca un neutral inventado).
"""
import re
from base64 import b64encode
from datetime import datetime, timezone

import requests

from config import (
    AI_VISIBILITY_MAX_OUTPUT_TOKENS, AI_VISIBILITY_MODEL, BRANDS,
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, get_ai_prompts, get_brand,
)
from pipeline.classifier import classify_texts

URL = "https://api.dataforseo.com/v3/ai_optimization/chat_gpt/llm_responses/live"


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def _call_model(prompt: str) -> dict | None:
    """
    Un llamado al modelo. Devuelve tasks[0] entero, o None si la
    respuesta no tiene ni siquiera esa forma — nunca lanza, un prompt que
    falla no debe tumbar el resto del set.
    """
    payload = [{
        "user_prompt": prompt,
        "model_name": AI_VISIBILITY_MODEL,
        "max_output_tokens": AI_VISIBILITY_MAX_OUTPUT_TOKENS,
    }]
    response = requests.post(URL, headers=_get_headers(), json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    try:
        return data["tasks"][0]
    except (KeyError, IndexError, TypeError):
        print("[DataForSEO AI Prompts] respuesta sin tasks")
        return None


def _extract_text(task_result: dict) -> str:
    """
    task["result"][0] -> texto plano concatenado de items[].sections[]
    (type="text"). Varias secciones (raro, pero el schema lo permite) se
    concatenan con salto de línea; ninguna sección de texto -> "".
    """
    partes = []
    for item in task_result.get("items") or []:
        for section in item.get("sections") or []:
            if section.get("type") == "text" and section.get("text"):
                partes.append(section["text"])
    return "\n".join(partes)


def _mentions_brand(text: str, keyword: str) -> int | None:
    """Índice del primer carácter donde aparece `keyword` como palabra
    completa (sin distinguir mayúsculas) en `text`, o None si no aparece."""
    match = re.search(r"\b" + re.escape(keyword) + r"\b", text, re.IGNORECASE)
    return match.start() if match else None


def _detect_and_rank(text: str, brands: list[dict]) -> dict[str, int | None]:
    """
    Para cada perfil en `brands`, el índice de su primera aparición en
    `text` (None si no aparece). No es todavía la "posición" final —
    _rank_positions() convierte estos índices en 1,2,3... entre los que
    sí aparecen.
    """
    return {b["name"]: _mentions_brand(text, b["keyword"]) for b in brands}


def _rank_positions(indices: dict[str, int | None]) -> dict[str, int | None]:
    presentes = sorted(
        (name for name, idx in indices.items() if idx is not None),
        key=lambda name: indices[name],
    )
    return {name: (presentes.index(name) + 1 if name in presentes else None)
            for name in indices}


def _classify_brand_mentions(text: str, brand_names_present: list[str]) -> dict[str, dict]:
    """
    Clasifica `text` UNA VEZ por cada marca presente (el prompt del
    clasificador está armado alrededor de una sola marca, ver
    pipeline/classifier.build_system_prompt) y devuelve
    {brand_name: resultado_o_None}. Marcas que no aparecen ni se
    clasifican — no hay sentimiento que sacarle a una marca de la que el
    texto no habla.
    """
    resultados = {}
    for name in brand_names_present:
        brand_profile = get_brand(name)
        clasificado = classify_texts([text], brand_profile)
        resultados[name] = clasificado[0] if clasificado else None
    return resultados


def scrape(brand: dict, since: str | None = None) -> list[dict]:
    """
    Corre TODO el set de prompts de `brand` (config.get_ai_prompts:
    preguntas de categoría + plantillas propias ya rellenadas) contra el
    modelo, y evalúa cada respuesta frente a `brand` y cada uno de sus
    competidores (brand["competitors"]).

    `since` no se usa (mismo motivo que en dataforseo_ai_visibility.scrape:
    esto no es una lista fechada de menciones) — se acepta solo para que
    la firma sea uniforme con el resto de scrapers.

    Devuelve una lista de {"response": {...}, "mentions": [...]}, un
    elemento por prompt, lista para pasar una a una a
    store.db.insert_ai_prompt_response(conn, item["response"],
    item["mentions"], run_id).
    """
    prompts = get_ai_prompts(brand["name"])
    competitor_names = brand.get("competitors") or []
    evaluated_brands = [brand] + [get_brand(n) for n in competitor_names if n in BRANDS]

    results = []
    for entry in prompts:
        prompt = entry["prompt"]
        task = _call_model(prompt)
        if not task or task.get("status_code") != 20000:
            print(f"[DataForSEO AI Prompts] prompt falló: {prompt!r} — "
                  f"{task.get('status_message') if task else 'sin respuesta'}")
            continue

        try:
            task_result = task["result"][0]
        except (KeyError, IndexError, TypeError):
            print(f"[DataForSEO AI Prompts] prompt sin result: {prompt!r}")
            continue

        text = _extract_text(task_result)
        if not text.strip():
            print(f"[DataForSEO AI Prompts] respuesta vacía: {prompt!r}")
            continue

        captured_at = datetime.now(timezone.utc).isoformat()
        indices = _detect_and_rank(text, evaluated_brands)
        positions = _rank_positions(indices)
        presentes = [name for name, idx in indices.items() if idx is not None]
        sentimientos = _classify_brand_mentions(text, presentes)

        mentions = []
        for eb in evaluated_brands:
            name = eb["name"]
            clasificado = sentimientos.get(name)
            mentions.append({
                "brand": name,
                "appears": indices[name] is not None,
                "position": positions[name],
                "sentiment_positive": clasificado["sentiment_positive"] if clasificado else None,
                "sentiment_negative": clasificado["sentiment_negative"] if clasificado else None,
                "sentiment_neutral": clasificado["sentiment_neutral"] if clasificado else None,
                "emotion": clasificado["emotion"] if clasificado else None,
                "classification_status": "classified" if clasificado else "unclassified",
            })

        results.append({
            "response": {
                "captured_at": captured_at,
                "platform": "chat_gpt",
                "model": task_result.get("model_name", AI_VISIBILITY_MODEL),
                "prompt": prompt,
                "prompt_scope": entry["scope"],
                "subject_brand": brand["name"] if entry["scope"] == "brand" else None,
                "response_text": text,
                "input_tokens": task_result.get("input_tokens"),
                "output_tokens": task_result.get("output_tokens"),
                "money_spent": task_result.get("money_spent"),
                "raw": task_result,
            },
            "mentions": mentions,
        })

    print(f"[DataForSEO AI Prompts] {len(results)}/{len(prompts)} prompts respondidos para "
          f"{brand['name']}")
    return results
