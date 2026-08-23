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
import re

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


# Los modelos (chat_gpt) y Google AI Overview devuelven markdown real:
# **negrita**, [texto](url), ![alt](url) (imagen — verificado en un
# ejemplo real de search_mentions para LATAM, ver .superpowers/
# visibilidad-ia.md), `código`, encabezados "### Título". Mostrado tal
# cual en una tarjeta de texto plano, el markdown sin renderizar es ruido
# visual (asteriscos, corchetes y backticks literales) que no aporta
# nada — se limpia acá, antes de truncar, para que la cita se lea como
# prosa. Esto es limpieza de FORMATO, no de contenido: no se toca ni una
# palabra del texto real, solo la sintaxis de marcado que ningún visor
# va a renderizar. El orden importa: la imagen (con "!") se resuelve
# ANTES que el link genérico, o el "!" se quedaría colgando sin su
# corchete.
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_HEADING = re.compile(r"^#{1,6}\s*", flags=re.MULTILINE)

# El cliente prohibió el guion largo en TODO texto que él vea (lo asocia
# con contenido generado por IA — ver tests/test_dashboard_visible_text.py).
# Estas respuestas las escribe un modelo, no nosotros, así que la regla no
# se puede garantizar en el origen: se normaliza acá, en la misma capa que
# ya limpia markdown y por el mismo motivo (es tipografía, no contenido —
# no se toca ni una palabra). Cubre también el guion medio (–, U+2013), que
# el modelo usa indistintamente. Sin esto, la primera respuesta con "—" que
# devuelva una captura futura llega intacta a la pantalla del cliente, y
# ahora que el desplegable muestra el texto COMPLETO (no un excerpt de 380
# caracteres) la superficie expuesta es varias veces mayor.
_DASHES = re.compile(r"[—–]")


def _strip_markdown(text: str) -> str:
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_CODE.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    return text


def _clean(text: str | None) -> str:
    """Texto listo para mostrar: sin sintaxis de markdown, sin guion largo
    y SIN truncar. Es lo que ve quien despliega la respuesta completa."""
    return _DASHES.sub("-", _strip_markdown((text or "").strip()))


def _excerpt(text: str | None) -> str:
    text = _clean(text)
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
        # Texto completo, para el desplegable "Leer la respuesta completa"
        # de la tarjeta (bloques 10c/10d). `excerpt` se conserva tal cual:
        # es la vista cerrada. Cuando la respuesta cabe en EXCERPT_LEN los
        # dos campos son idénticos, y esa igualdad es justamente la
        # condición que usa la plantilla para NO pintar el control.
        "response_full": _clean(row["response_text"]),
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
        # Mismo criterio que response_full: acá la pérdida era todavía
        # mayor (respuestas de hasta 5.300 caracteres recortadas a ~350).
        "answer_full": _clean(r["answer"]),
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


def _share_of_voice_by_engine(conn, brand_name: str) -> tuple[dict, bool, str | None]:
    """
    Volumen por intención y motor de UNA marca, de su captura más reciente.
    Se extrajo de build_share_of_voice_payload para poder correrla también
    sobre los competidores: sin el mismo indicador del competidor al lado,
    un 0,28% no es interpretable (no se compara contra cero, se compara
    contra quien pelea por el mismo pasajero) — ver la nota de lectura del
    bloque 11 en template.html.
    """
    run = db.latest_completed_run(conn, brand_name, "ai_visibility")
    rows = db.search_share_of_voice_for_brand(conn, brand_name) if run else []
    if run:
        rows = [r for r in rows if r["run_id"] == run["id"]]

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
        problema = engine_data["problema"]
        total = problema + engine_data["comercial"]
        # 2 decimales, no 1: con un decimal, Avianca (0,2845%) y LATAM
        # (0,0648%) se redondean a 0,3% y 0,1%, y esa diferencia real de
        # 4,4x se lee como 3x. El redondeo estaba borrando exactamente la
        # precisión que sostiene la comparación entre marcas.
        engine_data["problem_pct"] = round(problema / total * 100, 2) if total else None
        # El número protagonista del bloque: "1 de cada N búsquedas de la
        # marca es por un problema". 0,28% y 0,06% se leen los dos como
        # "casi nada"; 351 contra 1.543 se lee como una diferencia de
        # escala. None cuando no hay ninguna búsqueda de problema (no es
        # "1 de cada infinito", es que no hay dato que expresar así).
        engine_data["problem_one_in"] = round(total / problema) if problema else None

    return by_engine, bool(rows), (run["finished_at"] if run else None)


def build_share_of_voice_payload(conn, brand: str) -> dict:
    """
    Volumen de búsqueda por intención (problema vs. comercial) y motor
    (google_ads vs. ai_search) para `brand`, de la captura más reciente
    (mismo run_id que agrupa el resto de este bloque — ver docstring del
    módulo), más el mismo indicador de cada competidor del perfil.

    La comparación viaja DENTRO del payload de la marca propia (own vs.
    competitors), igual que en build_ai_visibility_payload — así la nota
    de lectura del dashboard se arma con datos, no con una frase fija que
    se rompería al entrar una tercera marca.
    """
    by_engine, has_data, captured_at = _share_of_voice_by_engine(conn, brand)

    competitors = []
    missing_competitors = []
    for name in get_brand(brand).get("competitors") or []:
        comp_engines, comp_has_data, comp_captured = _share_of_voice_by_engine(conn, name)
        if comp_has_data:
            competitors.append({
                "brand": name, "by_engine": comp_engines, "captured_at": comp_captured,
            })
        else:
            # Mismo criterio de honestidad que el resto del reporte: sin
            # captura se declara, nunca se rellena con 0.
            missing_competitors.append(name)

    return {
        "brand": brand,
        "by_engine": by_engine,
        "competitors": competitors,
        "missing_competitors": missing_competitors,
        "has_data": has_data,
        "captured_at": captured_at,
    }
