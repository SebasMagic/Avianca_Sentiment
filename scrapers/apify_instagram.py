"""
Apify Instagram scraper.
Fase 1: obtiene posts recientes de los perfiles de Instagram de la marca
(brand["instagram_profiles"]).
Fase 2: extrae comentarios de esos posts — son usuarios reales quejándose o elogiando.
Sentiment se procesa después en pipeline/classifier.py.

Tarea 2 del desglose de engagement: la Fase 1 trae, por post, likesCount,
commentsCount y (solo para posts de tipo Video) videoPlayCount — verificado
contra items reales del actor. Antes se descartaba todo salvo la URL. Ahora
se construye un mapa {post_url: {views, likes, comments}} y cada comentario
que sale de ese post se anota con las views del post, marcadas
reach_source='post' para dejar explícito que ese alcance es del CONTENEDOR,
no del comentario — decirlo de otra forma sería atribuirle a un comentario
un alcance que no le pertenece.

videoPlayCount NO existe en posts Sidecar (carrusel de imágenes) — Instagram
no expone reproducciones para contenido sin video. Para esos posts, views
queda None: no hay dato, no se inventa un cero.

Cuenta de origen del post (registro de procedencia): la Fase 1 también trae
"ownerUsername" — verificado contra un ítem real de la API (2026-08-20,
perfil @avianca): el mismo nombre de campo que usa la Fase 2 para el AUTOR
del comentario, pero a nivel de POST es la cuenta que lo publicó, no quien
comenta. Cuando una marca tiene varios perfiles configurados (p.ej. LATAM:
@latamairlines global vs. @latamairlines_colombia local), este es el único
dato que permite separar después qué cuenta originó cada comentario — se
guarda en post_reach junto a views/likes/comments y se adjunta a cada
comentario como "source_account". Si el post no está en el mapa (caso
borde), source_account queda None: no se inventa de qué cuenta salió.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import (
    APIFY_API_TOKEN, APIFY_INSTAGRAM_ACTOR, LIMIT_INSTAGRAM,
    INSTAGRAM_POSTS_LIMIT,
)


def _post_url_from_item(item: dict) -> str:
    """URL canónica de un ítem de post de Fase 1: 'url' si viene completa,
    si no se reconstruye desde 'shortCode'. Devuelve '' si no hay ninguno."""
    url = item.get("url", "") or ""
    if url.startswith("http"):
        return url
    shortcode = item.get("shortCode", "")
    return f"https://www.instagram.com/p/{shortcode}/" if shortcode else ""


def _post_reach_map(posts: list[dict]) -> dict[str, dict]:
    """
    {post_url: {views, likes, comments, owner_username}} a partir de items
    de Fase 1.

    views = videoPlayCount, que solo existe en posts type='Video' —
    verificado con datos reales (2026-08-20): un post Sidecar (carrusel de
    imágenes) no trae esa clave en absoluto, no la trae en 0. Para esos
    posts 'views' queda None.

    owner_username = "ownerUsername" del item de POST (verificado contra la
    API real, no confundir con el mismo nombre de campo en un item de
    COMENTARIO, que es el autor del comentario) — la cuenta que publicó
    el post. None si el item no lo trae.
    """
    reach = {}
    for p in posts:
        if "error" in p:
            continue
        url = _post_url_from_item(p)
        if not url:
            continue
        reach[url] = {
            "views": p.get("videoPlayCount"),
            "likes": p.get("likesCount"),
            "comments": p.get("commentsCount"),
            "owner_username": p.get("ownerUsername"),
        }
    return reach


def fetch_post_reach(post_urls: list[str]) -> dict[str, dict]:
    """
    Llama la Fase 1 del actor (resultsType='posts') para URLs de POST
    específicas (no perfiles). Usado por el backfill retroactivo de alcance
    (pipeline/instagram_reach_backfill.py, Tarea 2): una sola llamada de
    Fase 1 sobre posts que ya originaron comentarios guardados, sin volver
    a pedir comentarios (Fase 2), que ya están pagados.
    """
    if not post_urls:
        return {}
    client = ApifyClient(APIFY_API_TOKEN)
    run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": post_urls,
        "resultsType": "posts",
        "resultsLimit": len(post_urls),
    })
    posts = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return _post_reach_map(posts)


def scrape(brand: dict, since: str | None = None) -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)
    fetched_at = datetime.now(timezone.utc).isoformat()

    profiles = brand["instagram_profiles"]

    # ── FASE 1: obtener URLs de posts recientes + su alcance ──────
    print(f"[Instagram] Fase 1 — obteniendo posts de {brand['keyword']}...")
    posts_run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": profiles,
        "resultsType": "posts",
        "resultsLimit": INSTAGRAM_POSTS_LIMIT,
    })
    posts = list(client.dataset(posts_run["defaultDatasetId"]).iterate_items())

    post_reach = _post_reach_map(posts)
    post_urls = list(post_reach.keys())

    if not post_urls:
        print("[Instagram] Sin posts para extraer comentarios")
        return []

    print(f"[Instagram] {len(post_urls)} posts encontrados — Fase 2: extrayendo comentarios...")

    # ── FASE 2: extraer comentarios de esos posts ────────────────
    # post_urls ya viene acotado por INSTAGRAM_POSTS_LIMIT en Fase 1 (no
    # se trunca de nuevo aquí a 15).
    comments_run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input={
        "directUrls": post_urls,
        "resultsType": "comments",
        "resultsLimit": LIMIT_INSTAGRAM,
    })
    items = list(client.dataset(comments_run["defaultDatasetId"]).iterate_items())

    results = []
    for item in items:
        if "error" in item:
            continue

        text = item.get("text", "") or item.get("ownerUsername", "") or ""
        if not text.strip():
            continue

        timestamp = item.get("timestamp", "")
        if since and timestamp and str(timestamp)[:10] < since:
            continue

        # DEFECTO CORREGIDO (Task 8): la Fase 2 pide comentarios de VARIOS
        # posts a la vez (directUrls=post_urls), así que un mismo dataset
        # mezcla comentarios de todos ellos. El actor de Apify no expone
        # "url" en los ítems de tipo comentario (esa clave solo existe en
        # los ítems de tipo post de la Fase 1); confiar en item.get("url")
        # con fallback a post_urls[0] hacía que el 100% de los comentarios
        # cayeran a la URL del primer post, sin importar de cuál vinieran
        # realmente — eso fusionó personas distintas en el dedup por
        # fingerprint (mitigado en Task 4 incluyendo el autor, pero la
        # URL degenerada seguía siendo la causa raíz).
        #
        # Fix: usar "postUrl" (el post real al que pertenece el
        # comentario, según el schema del actor) con fallback a "url" por
        # compatibilidad, y sólo caer a post_urls[0] si el ítem no trae
        # ninguno de los dos. Sobre esa base, anexar "#comment-{id}" con
        # el id propio del comentario para que cada comentario tenga una
        # source_url distinta — sin esto, todos los comentarios de un
        # mismo post seguían colisionando entre sí. Si el ítem tampoco
        # trae "id", se cae al comportamiento anterior (source_url = URL
        # del post, compartida entre comentarios) en vez de inventar un
        # identificador falso.
        #
        # NO "simplificar" esto de vuelta a item.get("url", post_urls[0]):
        # eso fue el defecto original, verificado con datos reales de
        # Apify donde el 100% de 189 comentarios colisionaban en una sola
        # URL.
        #
        # post_url se calcula ANTES de la rama commentUrl/fallback porque
        # ahora también se usa para buscar el alcance del post contenedor
        # en post_reach (Tarea 2) — no solo para construir el fallback de
        # source_url.
        post_url = item.get("postUrl") or item.get("url") or (post_urls[0] if post_urls else "")
        reach = post_reach.get(post_url)
        views = reach.get("views") if reach else None
        # Cuenta que publicó el post contenedor (ver docstring del módulo y
        # de _post_reach_map) — None si el post no está en el mapa, nunca
        # inventado a partir del autor del comentario.
        source_account = reach.get("owner_username") if reach else None
        # reach_source solo se marca 'post' cuando SÍ hay un número real de
        # views que atribuirle — si el post es un Sidecar sin video, no hay
        # dato, y NULL (no 'post' con views=None) es lo honesto: 'post' sin
        # views implicaría que sabemos el alcance y es cero, y no es así.
        reach_source = "post" if views is not None else None
        #
        # Preferir "commentUrl": el actor lo entrega como un permalink real
        # y navegable (".../p/<shortcode>/c/<comment_id>"), que Instagram sí
        # interpreta como ancla al comentario. Verificado con datos reales:
        # el 100% de 909 filas de Instagram lo traen. La construcción manual
        # "{post_url}#comment-{id}" de abajo NO es una URL que Instagram
        # entienda como ancla — solo abre el post, nunca el comentario — así
        # que se conserva únicamente como fallback si el ítem no trae
        # commentUrl (p.ej. una versión vieja del actor).
        comment_url = item.get("commentUrl")
        if comment_url:
            source_url = comment_url
        else:
            comment_id = item.get("id")
            source_url = f"{post_url}#comment-{comment_id}" if comment_id else post_url

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "instagram",
            "source_url": source_url,
            "text": text,
            "author": item.get("ownerUsername", None),
            # Cuenta de Instagram que publicó el POST del que salió este
            # comentario (ver docstring del módulo) — no confundir con
            # "author" (quien escribió el comentario).
            "source_account": source_account,
            "published_at": timestamp or None,
            "country": "CO",
            "likes": item.get("likesCount", 0) or 0,
            "shares": 0,
            "comments_count": 0,
            # Un comentario no tiene saves propios — no es límite del
            # actor, es qué ES un comentario (ver Tarea 1). views/
            # reach_source sí pueden venir del post contenedor (Tarea 2).
            "saves": None,
            "views": views,
            "reach_source": reach_source,
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "is_complaint": False,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[Instagram] {len(results)} comentarios extraídos")
    return results
