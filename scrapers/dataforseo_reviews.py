"""
DataForSEO Trustpilot Reviews scraper — reseñas post-vuelo, con estrella.

Endpoint verificado contra la API real (2026-08-21/22), ASÍNCRONO
(task_post -> esperar -> task_get):

    POST .../v3/business_data/trustpilot/reviews/task_post
      [{"domain": brand["review_domain"], "depth": config.LIMIT_REVIEWS}]
    GET  .../v3/business_data/trustpilot/reviews/task_get/{id}

Costo real observado: $0,00075 por task_post (depth=20) — task_get es
gratis (cost=0 en la respuesta), se puede reintentar sin gastar de
nuevo. Tiempo de espera real observado: Avianca resolvió al primer
intento (~3s), LATAM tardó 4 intentos (~29s, status_code=40602 "Task In
Queue" en los tres primeros) — se resuelve con reintentos de backoff
creciente (_poll_result), nunca con un sleep fijo largo.

Las reseñas de Trustpilot del dominio propio de la marca son
inherentemente relevantes (decisión del usuario, ver pipeline/
relevance.py): is_relevant() no tiene rama "resena" — el catch-all la
deja pasar sin evaluar, igual que "instagram". No hay forma de que
Trustpilot le atribuya al dominio de la marca una reseña que no sea
sobre ella.

`rating` (entero 1-5, ver item["rating"]["value"]) viaja en su propia
columna del schema unificado (store/db.py, migración aditiva) — NULL
para cualquier plataforma que no sea "resena".

Sin clasificación en este módulo: sentiment/emotion/is_complaint quedan
sin poblar, a la espera de pipeline/classify_pending.py — "Ambas fuentes
pasan por el clasificador con los mismos drivers" (ver .superpowers/
prensa-resenas.md, Tarea 3).
"""
import time
import uuid
from base64 import b64encode
from datetime import datetime, timezone

import requests

from config import DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD, LIMIT_REVIEWS

# Backoff de reintento para task_get — Fibonacci-like, verificado con
# datos reales: Avianca resolvió al primer intento (~3s de espera antes
# del primer poll), LATAM tardó 4 intentos (~29s acumulados). Suma ~50s
# de techo antes de rendirse — deliberadamente varios reintentos cortos,
# no un único sleep largo, para no bloquear el proceso si la tarea nunca
# termina.
POLL_WAITS = [3, 5, 8, 13, 21]

# status_code de DataForSEO para "todavía procesando" — cualquier otro
# status_code distinto de 20000 (Ok) se trata como error real, no como
# "seguir esperando".
_PENDING_STATUS_CODES = {40601, 40602}


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def _post_task(domain: str) -> str | None:
    """Encola la tarea de scraping de reseñas. Devuelve el task id, o
    None si la API no lo aceptó (se loguea el motivo, no se lanza — un
    fallo acá no debe tumbar el resto del pipeline de la corrida)."""
    payload = [{"domain": domain, "depth": LIMIT_REVIEWS}]
    response = requests.post(
        "https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_post",
        headers=_get_headers(), json=payload, timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    try:
        task = data["tasks"][0]
    except (KeyError, IndexError, TypeError):
        print("[DataForSEO Reviews] Respuesta sin tasks en task_post")
        return None
    # 20000 (Ok) o 20100 (Task Created) son ambos "se encoló bien" —
    # verificado con datos reales: task_post devolvió 20100.
    if task.get("status_code") not in (20000, 20100):
        print(f"[DataForSEO Reviews] task_post falló: {task.get('status_message')}")
        return None
    return task.get("id")


def _poll_result(task_id: str) -> list[dict]:
    """Reintenta task_get con backoff creciente hasta que la tarea
    termine (status_code=20000) o se agoten los reintentos. Devuelve los
    items crudos, o [] si nunca terminó o falló."""
    for wait in POLL_WAITS:
        time.sleep(wait)
        response = requests.get(
            f"https://api.dataforseo.com/v3/business_data/trustpilot/reviews/task_get/{task_id}",
            headers=_get_headers(), timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        try:
            task = data["tasks"][0]
        except (KeyError, IndexError, TypeError):
            continue

        status = task.get("status_code")
        if status == 20000:
            try:
                return task["result"][0]["items"] or []
            except (KeyError, IndexError, TypeError):
                return []
        if status not in _PENDING_STATUS_CODES:
            print(f"[DataForSEO Reviews] task_get falló: {task.get('status_message')}")
            return []
        # status pendiente ("Task In Queue" / "In Progress") — sigue el loop

    print(f"[DataForSEO Reviews] task {task_id} no terminó tras "
          f"{sum(POLL_WAITS)}s de reintentos — se omite esta corrida")
    return []


def _parse_timestamp(raw: str | None) -> str | None:
    """Mismo formato que scrapers/dataforseo_news.py — verificado en la
    misma corrida de datos reales. None si falta o no parsea."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z").isoformat()
    except ValueError:
        return None


def _parse_rating(raw: dict | None) -> int | None:
    """item["rating"]["value"] -> entero 1-5. None si falta o no es
    numérico — nunca se inventa una estrella."""
    value = (raw or {}).get("value")
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def scrape(brand: dict, since: str | None = None) -> list[dict]:
    """
    Reseñas de Trustpilot para brand["review_domain"], en el schema
    unificado (platform="resena"). `since` (YYYY-MM-DD) filtra del lado
    del cliente — el endpoint no soporta rango de fechas; None no filtra
    nada.
    """
    domain = brand.get("review_domain")
    if not domain:
        print(f"[DataForSEO Reviews] {brand.get('name')} no tiene "
              f"review_domain configurado — se omite")
        return []

    task_id = _post_task(domain)
    if not task_id:
        return []

    items = _poll_result(task_id)
    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []

    for item in items:
        review_text = (item.get("review_text") or "").strip()
        title = (item.get("title") or "").strip()
        if title and review_text:
            text = f"{title}. {review_text}"
        else:
            text = review_text or title
        if not text.strip():
            continue

        published_at = _parse_timestamp(item.get("timestamp"))
        if since and published_at and published_at[:10] < since:
            continue

        user = item.get("user_profile") or {}

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "resena",
            "source_url": item.get("url") or None,
            "text": text,
            "author": user.get("name") or None,
            "published_at": published_at,
            "country": user.get("location") or None,
            "likes": 0,
            "shares": 0,
            "comments_count": 0,
            "rating": _parse_rating(item.get("rating")),
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[DataForSEO Reviews] {len(results)} reseñas extraídas para {domain}")
    return results
