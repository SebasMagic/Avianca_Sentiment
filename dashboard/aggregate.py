"""
Agregaciones para el dashboard. Lee la DB y produce el payload JSON.

Sin HTML, sin red. Cinco reglas que no se negocian, en el orden en que se
aplican:

  - Antes que nada, se descartan las menciones anteriores a
    REPORT_WINDOW_START (config.py). El backfill se pidió con
    --since 2026-04-19, pero el actor de TikTok (clockworks/tiktok-scraper)
    ignoró oldestPostDate y devolvió igual 24 videos de 2023-2025 — reales,
    ya pagados, pero que estiraban el timeline sobre 41 meses con el 98% de
    los datos concentrados en 6. Se aplica UNA sola vez, aquí, a TODO el
    análisis (KPIs, timeline, drivers, sentimiento, emociones, tabla, top
    quejas) para que los números reconcilien entre bloques — no hay
    excepciones por bloque. Las menciones sin published_at (fecha
    desconocida) NO se filtran por esta regla — no hay fecha con la cual
    juzgarlas contra la ventana, y ya tienen su propio tratamiento (la
    regla del timeline, más abajo, y se cuentan en data_quality.unknown_date).
  - Sobre lo que queda dentro de la ventana, se descartan las menciones con
    `exclusion_reason` — dos motivos distintos, la misma columna:
      (a) filas de TikTok (resultado de búsqueda por hashtag) que
          pipeline/relevance.py o el backfill retroactivo
          (pipeline/social_relevance_backfill.py, Tarea 3) marcaron como
          irrelevantes: mencionan la marca por coincidencia pero no hablan
          de ella (caso real: "#latam" trajo 29 videos, 28 eran memes de
          Latinoamérica sin relación con la aerolínea).
      (b) filas de platform='web' (Cambio 1, retiro del canal web) que
          pipeline/web_channel_retirement.py marcó con
          config.WEB_CHANNEL_RETIREMENT_REASON — decisión de política, no
          una evaluación caso por caso: 71 menciones web entre las dos
          marcas producían solo 2 quejas reales, y la capa completa es
          ~95% agregadores de vuelos y ruido no relacionado (ver el
          docstring de ese módulo para el detalle).
    Igual que con la ventana de reporte, la fila SIGUE en la DB —
    auditable, reversible si la decisión cambia — pero no cuenta en
    ningún bloque. Los dos motivos se cuentan por separado en
    data_quality (excluded_irrelevant vs. excluded_web_retired) porque
    son decisiones de naturaleza distinta y el bloque 8 los explica con
    textos distintos.
  - Sobre lo que queda, las menciones se colapsan por (author, text) en
    "voces" únicas. Una persona real que pega el mismo comentario 48
    veces (caso medido: alejandra.caicho, 56 filas, 56 source_url de
    comentario distintas y reales) es una queja, no 48. Sin colapsar, un
    puñado de spammers reescribe la distribución de drivers: con los
    1.261 registros crudos de este proyecto, atencion_cliente pasa de
    representar 32,8% de las quejas a solo 26-27% una vez colapsado, y
    "otro" sube de 20,4% a ~26%. El scraper no está mal — cada fila es una
    URL de comentario real — el problema es puramente analítico: contar
    personas, no apariciones. La insistencia del autor no se descarta, se
    reexpone como `repeat_count` en cada voz.
  - El timeline ignora las menciones con date_confidence 'unknown'.
    Meterlas falsearía la serie temporal, que es justo lo que pasó en v1.
  - Los promedios de sentiment ignoran las 'unclassified'. Contarlas
    como neutral inventaría neutralidad que nadie midió.

Todos los bloques (KPIs, timeline, drivers, driver×plataforma, sentiment,
emociones, tabla y top quejas) trabajan sobre las voces ya colapsadas,
dentro de la ventana de reporte.

Multi-marca: build_payload(conn, brand=...) acota todo lo anterior a una
sola marca; build_payload(conn, brand=None) NO filtra — agrega TODAS las
marcas juntas (vista combinada). Ningún bloque de este módulo asume marca
única: ninguno lee config.BRANDS ni compara contra una marca fija en
ningún punto de la agregación, así que un dataset con Avianca y LATAM
mezclados se agrega igual de bien que uno de una sola marca. El colapso de
voces (_collapse_voices) agrupa por (brand, author, text) — no solo
(author, text) — precisamente para que, en la vista combinada, dos
personas de marcas distintas diciendo lo mismo no se fusionen en una sola
voz.
"""
import collections

from config import REPORT_WINDOW_START, WEB_CHANNEL_RETIREMENT_REASON
from store import db

# "web" queda FUERA a propósito (Cambio 1, retiro del canal web) — nunca
# vuelve a aparecer una voz de esa plataforma en ningún bloque (ver
# pipeline/web_channel_retirement.py: todas las filas platform='web' ya
# guardadas quedan con exclusion_reason). Si esta lista siguiera incluyendo
# "web", el timeline y la cobertura por plataforma (bloque 8) mostrarían una
# columna "Web" siempre en cero, colgando sin datos.
PLATFORMS = ["instagram", "tiktok"]

# Qué métricas de engagement tiene sentido mostrar por plataforma —
# diagnóstico verificado sobre datos reales (2026-08-20, ver
# docs/superpowers/specs/2026-08-19-avianca-sentiment-4meses-design.md y
# pipeline/engagement_enrichment.py):
#
#   web:       DataForSEO nunca entrega ninguna métrica de engagement.
#   tiktok:    diggCount/commentCount/shareCount/collectCount/playCount son
#              del video mismo — las cinco métricas aplican, alcance
#              PROPIO (reach_source='propio').
#   instagram: cada mención ES un comentario. likesCount es el like propio
#              del comentario; comments_count y shares NO aplican — un
#              comentario no tiene comentarios propios ni se comparte
#              (repliesCount viene NULL en el 100% de los items reales) —
#              tampoco tiene saves.
#
# `views` y `post_reach` son DOS métricas distintas a propósito, no una
# con dos fuentes — encontrado en revisión de código (2026-08-20):
# mezclarlas bajo un solo campo "views" hacía que quince comentarios bajo
# el mismo post de Instagram mostraran cada uno el alcance TOTAL de ese
# post (7,3M), lo cual (a) no sirve para rankear comentarios porque es
# constante dentro del post — ordena posts, no quejas; (b) no es
# comparable con el alcance propio de TikTok, que sí es del ítem; y
# (c) al sumarse entre repeticiones de una voz colapsada, multiplicaba la
# MISMA audiencia por cada vez que la persona comentó ese post.
#
#   views:      SOLO alcance propio del ítem (reach_source='propio') —
#               aplica a tiktok, nunca a instagram ni a web. Es la métrica
#               que se rankea y se compara entre menciones.
#   post_reach: visibilidad HEREDADA del post contenedor
#               (reach_source='post') — aplica a instagram, nunca a tiktok
#               ni a web. Es CONTEXTO ("dónde apareció esta queja"), nunca
#               se presenta como si fuera el alcance de la mención, nunca
#               se suma junto con `views`, y se deduplica por post antes
#               de sumar entre repeticiones de una misma voz (ver
#               _post_reach_sum).
#
# Esto declara qué CONCEPTO existe por plataforma, no si el valor guardado
# es cero: una métrica que no aplica se fuerza a None (guion en el
# dashboard) aunque la columna tenga un 0 heredado del schema — "las que
# no aplican van con guion, no con cero".
#
# "web" ya no tiene entrada (Cambio 1, retiro del canal web) — nunca tuvo
# ninguna métrica de todos modos (ver el comentario de arriba: DataForSEO
# nunca entregó engagement). _apply_metric() usa
# METRIC_APPLIES.get(platform, {}) — la ausencia de "web" aquí produce
# exactamente el mismo resultado (todo None) que la entrada explícita que
# había antes, así que quitarla no cambia el comportamiento si alguna vez
# quedara una fila suelta sin marcar; solo evita declarar una plataforma
# que ya no se reporta.
METRIC_APPLIES = {
    "tiktok":    {"likes": True,  "shares": True,  "comments_count": True,  "saves": True,  "views": True,  "post_reach": False},
    "instagram": {"likes": True,  "shares": False, "comments_count": False, "saves": False, "views": False, "post_reach": True},
}

ENGAGEMENT_METRICS = ("likes", "shares", "comments_count", "saves", "views", "post_reach")


def _engagement(m: dict) -> int:
    return (m.get("likes") or 0) + (m.get("shares") or 0) + (m.get("comments_count") or 0)


def _sum_maybe(values) -> int | None:
    """
    Suma ignorando None; si TODOS los valores son None, el resultado es
    None, no 0 — la ausencia de dato (nunca medido) no es lo mismo que
    medir un cero real. Usado para saves/views, que sí pueden ser NULL.
    """
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def _apply_metric(platform: str, metric: str, value):
    """None si `metric` no aplica a `platform` (ver METRIC_APPLIES) — el
    valor tal cual si aplica, que a su vez puede ser None si simplemente
    no se midió para estas filas."""
    return value if METRIC_APPLIES.get(platform, {}).get(metric, False) else None


def _interaction_rate(interactions, views) -> float | None:
    """
    interacciones ÷ alcance PROPIO, en %. Deliberadamente NUNCA usa
    post_reach como denominador: dividir las interacciones de UN
    comentario entre la audiencia total de TODO el post en el que aparece
    exageraría o diluiría la tasa sin decir nada real sobre ese comentario
    — el mismo tipo de error que mezclar `views` y `post_reach` en un solo
    campo (ver METRIC_APPLIES). Consecuencia: interaction_rate es siempre
    None en Instagram (nunca tiene alcance propio) — es más conservador
    que antes, pero antes era una tasa engañosa, no una tasa real.

    None si no hay alcance propio medido (views None o 0) o no hay
    interacciones que dividir — nunca ZeroDivisionError, y un alcance de 0
    no produce una tasa (dividir por cero no es "0%").
    """
    if not views or interactions is None:
        return None
    return round(interactions / views * 100, 1)


def _post_reach_sum(group: list[dict]) -> int | None:
    """
    Visibilidad heredada del post (reach_source='post'), sumada SIN
    duplicar. Si esta voz comentó varias veces bajo el MISMO post, ese
    post cuenta una sola vez — la audiencia del post no crece porque la
    misma persona haya comentado más veces, a diferencia de likes o
    engagement, que sí son acciones distintas y aditivas. Si comentó en
    posts DISTINTOS, cada post distinto sí aporta su propia visibilidad,
    una vez cada uno.

    Deduplicación por raw['postUrl'] — el identificador real del post en
    el JSON crudo de Instagram (ver scrapers/apify_instagram.py, Tarea 2).
    Un registro con reach_source='post' pero sin postUrl en su raw (no
    debería ocurrir: es exactamente el campo que Tarea 2 usa para calcular
    ese valor) se trata como un post no identificable y no se deduplica
    contra nada — mejor no perder el dato que fusionarlo con el post
    equivocado.
    """
    por_post: dict = {}
    for i, m in enumerate(group):
        if m.get("reach_source") != "post":
            continue
        v = m.get("views")
        if v is None:
            continue
        post_key = (m.get("raw") or {}).get("postUrl") or ("__sin_posturl__", i)
        por_post.setdefault(post_key, v)
    return sum(por_post.values()) if por_post else None


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _in_report_window(m: dict) -> bool:
    """
    True si la mención entra en la ventana de reporte (REPORT_WINDOW_START,
    config.py). Sin published_at no hay fecha con la cual evaluarla contra
    la ventana, así que se conserva — el filtro solo excluye lo que
    SABEMOS que es anterior, no lo que no sabemos fechar.
    """
    published_at = m.get("published_at")
    if not published_at:
        return True
    return published_at[:10] >= REPORT_WINDOW_START


def _is_excluded(m: dict) -> bool:
    """
    True si la mención tiene CUALQUIER `exclusion_reason` — irrelevancia
    social (Tarea 3) o retiro del canal web (Cambio 1), ver docstring del
    módulo. La fila sigue en la DB, esto solo decide si CUENTA en el
    reporte. Usado para construir `relevant_mentions`; el desglose por
    motivo (para data_quality) vive en _is_web_retirement()/más abajo, no
    aquí — este chequeo es deliberadamente ciego al motivo concreto.
    """
    return bool(m.get("exclusion_reason"))


def _is_web_retirement(m: dict) -> bool:
    """
    True si el motivo de exclusión es específicamente el retiro del canal
    web (Cambio 1) — distingue esta fila de una excluida por irrelevancia
    social de TikTok (Tarea 3), que usa otros valores de exclusion_reason
    ("sin_keyword", "sin_contexto_aeronautico"). Ambas cuentan para
    `_is_excluded`, pero se reportan por separado en data_quality porque
    son decisiones de naturaleza distinta y el bloque 8 las explica con
    textos distintos.
    """
    return m.get("exclusion_reason") == WEB_CHANNEL_RETIREMENT_REASON


def _collapse_voices(mentions: list[dict]) -> list[dict]:
    """
    Agrupa menciones por (author, text) — la misma persona diciendo lo mismo,
    sin importar en qué source_url quedó cada repetición — y devuelve una
    "voz" por grupo.

    De cada grupo se conserva la ocurrencia más antigua por published_at
    (NULL cuenta como la más reciente, para que una fecha ausente no gane
    por accidente el puesto de "primera vez que se vio"), y se le añaden:

      - repeat_count: tamaño del grupo (1 si no se repitió).
      - engagement:   suma de likes+shares+comments_count de TODAS las
                       repeticiones — una queja spammeada sí acumula
                       alcance real, aunque el texto sea el mismo. Se
                       conserva tal cual para no romper nada; ya NO se
                       presenta como la medida de impacto (ver las tres
                       capas más abajo: likes/shares/comments_count/saves/
                       views, interactions e interaction_rate).
      - likes/shares/comments_count/saves: suma por métrica de TODAS las
        repeticiones, forzada a None cuando la métrica no aplica a la
        plataforma (METRIC_APPLIES) — "las que no aplican van con guion,
        no con cero". saves usa _sum_maybe: si NINGUNA repetición tiene el
        dato, el total es None, no 0.
      - views (alcance PROPIO): suma SOLO de las repeticiones con
        reach_source='propio' — nunca mezcla con visibilidad heredada de
        post. Aditivo entre repeticiones porque cada una es, en la
        práctica, un ítem propio distinto (p.ej. varios videos de TikTok
        del mismo autor) con su propia audiencia.
      - post_reach (visibilidad HEREDADA del post): ver _post_reach_sum.
        NUNCA se suma con `views`, y se deduplica por post — comentar 48
        veces bajo el mismo post no multiplica por 48 la audiencia de ese
        post (corregido: antes `views` mezclaba ambos conceptos bajo un
        solo campo y sí los sumaba por repetición, inflando voces como
        alejandra.caicho x48 a una cifra sin sentido).
      - reach_source: 'propio' si `views` quedó con dato, si no 'post' si
        `post_reach` quedó con dato, si no None. Ya no se lee de una
        ocurrencia puntual del grupo — se deriva de cuál de los dos
        totales (ya deduplicados/sumados arriba) terminó con valor.
      - interactions: likes+comments_count+shares+saves ya sumados y
        filtrados por plataforma — None si ninguna métrica aplica (caso
        web) o ninguna tiene dato. NUNCA incluye views ni post_reach —
        alcance e interacciones son capas separadas, no se mezclan.
      - interaction_rate: interactions ÷ views (alcance PROPIO), nunca
        ÷ post_reach — ver docstring de _interaction_rate.

    Autores distintos con el mismo texto NO se colapsan: el fingerprint de
    la DB ya incluye el autor exactamente para poder distinguir a dos
    personas distintas citando la misma frase (ver store/db.py). Colapsar
    por texto solo, ignorando el autor, fusionaría voces reales.

    La clave de agrupación incluye `brand` (no solo author+text): en una
    llamada con brand=None (vista combinada, Tarea 1) las menciones de
    Avianca y de LATAM viajan en la misma lista, y sin la marca en la
    clave dos personas DISTINTAS de marcas distintas que por coincidencia
    escriben exactamente el mismo texto se fusionarían en una sola voz.
    Cuando el payload ya viene filtrado a una sola marca, `brand` es
    constante en todas las filas y esta clave se comporta exactamente
    igual que antes (author, text).
    """
    groups: "collections.OrderedDict[tuple, list[dict]]" = collections.OrderedDict()
    for m in mentions:
        key = (m.get("brand"), m.get("author"), m.get("text"))
        groups.setdefault(key, []).append(m)

    def _sort_key(m: dict):
        # NULL published_at ordena al final tanto para "más antigua" (abajo)
        # como para el orden final descendente (también al final).
        return (m.get("published_at") is None, m.get("published_at") or "")

    voices = []
    for _, group in groups.items():
        oldest = min(group, key=_sort_key)
        voice = dict(oldest)
        voice["repeat_count"] = len(group)
        voice["engagement"] = sum(_engagement(m) for m in group)

        platform = voice["platform"]
        likes = _apply_metric(platform, "likes", sum(m.get("likes") or 0 for m in group))
        shares = _apply_metric(platform, "shares", sum(m.get("shares") or 0 for m in group))
        comments_count = _apply_metric(
            platform, "comments_count", sum(m.get("comments_count") or 0 for m in group))
        saves = _apply_metric(platform, "saves", _sum_maybe(m.get("saves") for m in group))

        # Alcance PROPIO: solo ocurrencias con reach_source='propio'. Nunca
        # se mezcla con la visibilidad heredada del post (post_reach).
        own_reach_values = [m.get("views") for m in group if m.get("reach_source") == "propio"]
        views = _apply_metric(platform, "views", _sum_maybe(own_reach_values))

        # Visibilidad HEREDADA del post — deduplicada por post, nunca
        # sumada por repetición de la misma voz en el mismo post.
        post_reach = _apply_metric(platform, "post_reach", _post_reach_sum(group))

        voice["likes"] = likes
        voice["shares"] = shares
        voice["comments_count"] = comments_count
        voice["saves"] = saves
        voice["views"] = views
        voice["post_reach"] = post_reach
        voice["reach_source"] = (
            "propio" if views is not None else ("post" if post_reach is not None else None)
        )

        interactions = _sum_maybe([likes, comments_count, shares, saves])
        voice["interactions"] = interactions
        voice["interaction_rate"] = _interaction_rate(interactions, views)

        voices.append(voice)

    # Mismo orden que store.db.all_mentions(): más reciente primero.
    voices.sort(key=_sort_key, reverse=True)
    return voices


def _dominant_label(m: dict) -> str:
    """
    Etiqueta de sentiment dominante de UNA mención: la de mayor probabilidad
    entre positive/negative/neutral. Contar por etiqueta dominante (en vez
    de promediar probabilidades) es lo que permite decir "el 52,6% de las
    menciones son positivas" y que esa frase signifique lo que dice —
    promediar probabilidades no sostiene esa lectura (ver docstring de
    build_payload / Cambio 2).

    Desempate (probabilidades exactamente iguales, caso raro pero posible):
    gana negative sobre neutral sobre positive. Un empate no se disuelve
    en la lectura más favorable — se resuelve hacia la señal más accionable
    para un director de servicio, que es la negativa.
    """
    pos = m.get("sentiment_positive") or 0
    neg = m.get("sentiment_negative") or 0
    neu = m.get("sentiment_neutral") or 0
    candidatos = [("negative", neg), ("neutral", neu), ("positive", pos)]
    return max(candidatos, key=lambda par: par[1])[0]


def build_payload(conn, brand: str | None = None) -> dict:
    """
    `brand`: nombre de marca (ver config.BRANDS) para acotar todo el
    payload a esa marca, o None para NO filtrar — agrega TODAS las marcas
    presentes en la DB juntas (vista combinada). Ver docstring del módulo.
    """
    raw_mentions = db.all_mentions(conn, brand=brand)

    # Ventana de reporte — ver docstring del módulo y config.REPORT_WINDOW_START.
    # Se aplica UNA vez aquí, antes de colapsar voces, para que todo lo que
    # sigue (KPIs, timeline, drivers, sentimiento, emociones, tabla, top
    # quejas) trabaje sobre el mismo conjunto y los números reconcilien.
    windowed_mentions = [m for m in raw_mentions if _in_report_window(m)]
    outside_window = len(raw_mentions) - len(windowed_mentions)

    # Exclusiones por exclusion_reason (relevancia social Tarea 3 + retiro
    # del canal web Cambio 1) — ver docstring del módulo. Se aplica DESPUÉS
    # de la ventana de reporte (para no cambiar outside_window, que sigue
    # siendo "cuántas quedan fuera de fecha" tal cual estaba) y ANTES de
    # colapsar voces — una mención excluida no debe aportar su
    # repeat_count/engagement a una voz que sí cuenta.
    relevant_mentions = [m for m in windowed_mentions if not _is_excluded(m)]

    excluded_mentions = [m for m in windowed_mentions if _is_excluded(m)]
    # Los dos motivos se cuentan por separado — ver _is_web_retirement().
    excluded_web_retired_mentions = [m for m in excluded_mentions if _is_web_retirement(m)]
    excluded_irrelevant_mentions = [m for m in excluded_mentions if not _is_web_retirement(m)]

    excluded_irrelevant = len(excluded_irrelevant_mentions)
    excluded_irrelevant_reasons = dict(collections.Counter(
        m["exclusion_reason"] for m in excluded_irrelevant_mentions
    ))
    excluded_web_retired = len(excluded_web_retired_mentions)

    mentions = _collapse_voices(relevant_mentions)
    collapsed_repeats = len(relevant_mentions) - len(mentions)
    total = len(mentions)

    complaints = [m for m in mentions if m["is_complaint"]]
    classified = [m for m in mentions if m["classification_status"] == "classified"]
    dated = [m for m in mentions if m["date_confidence"] != "unknown" and m["published_at"]]

    # ── Sentiment: conteo por etiqueta dominante (lo que se muestra) y
    # promedio de probabilidades (se conserva por si sirve, no se muestra).
    if classified:
        avg_pos = sum(m["sentiment_positive"] or 0 for m in classified) / len(classified)
        avg_neg = sum(m["sentiment_negative"] or 0 for m in classified) / len(classified)
        avg_neu = sum(m["sentiment_neutral"] or 0 for m in classified) / len(classified)
    else:
        avg_pos = avg_neg = 0.0
        avg_neu = 1.0

    label_counts = collections.Counter(_dominant_label(m) for m in classified)
    n_classified = len(classified)
    sent_counts = {
        "positive": label_counts["positive"],
        "negative": label_counts["negative"],
        "neutral": label_counts["neutral"],
    }
    sent_pct = {k: _pct(v, n_classified) for k, v in sent_counts.items()}

    # ── KPIs
    fechas = sorted(m["published_at"][:10] for m in dated)

    kpis = {
        "total": total,
        "complaints": len(complaints),
        "complaint_rate": _pct(len(complaints), total),
        # Neto sobre etiquetas dominantes, coherente con lo que se muestra
        # en todo el resto del dashboard (ya no promedio de probabilidades).
        "net_sentiment": round(sent_pct["positive"] - sent_pct["negative"], 1),
        "date_from": fechas[0] if fechas else None,
        "date_to": fechas[-1] if fechas else None,
        "sources": len({m["platform"] for m in mentions}),
    }

    # ── Timeline (solo fechas confiables)
    por_dia = collections.defaultdict(lambda: collections.Counter())
    sent_dia = collections.defaultdict(list)
    for m in dated:
        dia = m["published_at"][:10]
        por_dia[dia][m["platform"]] += 1
        if m["classification_status"] == "classified":
            sent_dia[dia].append((m["sentiment_positive"] or 0) - (m["sentiment_negative"] or 0))

    timeline = []
    for dia in sorted(por_dia):
        muestras = sent_dia.get(dia, [])
        timeline.append({
            "date": dia,
            "counts": {p: por_dia[dia].get(p, 0) for p in PLATFORMS},
            "net_sentiment": round(sum(muestras) / len(muestras) * 100, 1) if muestras else None,
        })

    # ── Drivers
    conteo_driver = collections.Counter(
        m["complaint_driver"] for m in complaints if m["complaint_driver"]
    )
    drivers = [
        # pct = peso del driver sobre el total de quejas. Se reutiliza tal
        # cual para la columna "% Total" del heatmap driver×plataforma
        # (bloque 4) — el JS la busca por nombre de driver en vez de
        # recalcularla a mano desde la grilla.
        {"driver": d, "count": c, "pct": _pct(c, len(complaints))}
        for d, c in conteo_driver.most_common()
    ]

    # ── Driver × plataforma
    cruce = collections.Counter(
        (m["complaint_driver"], m["platform"])
        for m in complaints if m["complaint_driver"]
    )
    driver_by_platform = [
        {"driver": d, "platform": p, "count": c}
        for (d, p), c in sorted(cruce.items())
    ]

    # ── Drivers por mes (tendencia)
    por_mes = collections.Counter(
        (m["published_at"][:7], m["complaint_driver"])
        for m in complaints
        if m["complaint_driver"] and m["published_at"] and m["date_confidence"] != "unknown"
    )
    driver_trend = [
        {"month": mes, "driver": d, "count": c}
        for (mes, d), c in sorted(por_mes.items())
    ]

    # ── Emociones
    emotions = dict(collections.Counter(
        m["emotion"] for m in classified if m["emotion"]
    ))

    # ── Tabla y top quejas
    filas = [{
        "id": m["id"],
        # Marca de esta voz — sale directo de la fila (dict(oldest) en
        # _collapse_voices ya la trae). Necesaria para que la vista
        # combinada (brand=None) pueda distinguir de qué marca es cada
        # fila de la tabla o cada card de top quejas; en un payload
        # filtrado a una sola marca es simplemente constante.
        "brand": m.get("brand"),
        "platform": m["platform"],
        "text": m["text"],
        "author": m["author"],
        "published_at": m["published_at"],
        "date_confidence": m["date_confidence"],
        "source_url": m["source_url"],
        "is_complaint": bool(m["is_complaint"]),
        "complaint_driver": m["complaint_driver"],
        "emotion": m["emotion"],
        "sentiment_negative": m["sentiment_negative"],
        # m["engagement"] ya viene sumado por _collapse_voices (todas las
        # repeticiones de la voz); NO recalcular con _engagement(m) aquí,
        # porque eso volvería a leer solo likes/shares/comments de la
        # ocurrencia más antigua y perdería el alcance de las repeticiones.
        # Se conserva tal cual — ya NO es la medida de impacto que se
        # presenta (ver las tres capas: alcance/interacciones/tasa abajo).
        "engagement": m["engagement"],
        "repeat_count": m["repeat_count"],
        # ── Las capas de engagement: alcance PROPIO (views), visibilidad
        # HEREDADA del post (post_reach — contexto, nunca alcance de la
        # mención), interacciones (likes+comments+shares+saves) y tasa de
        # interacción — nunca sumadas entre sí en un número compuesto, y
        # views/post_reach nunca se mezclan entre sí (ver METRIC_APPLIES).
        # None = la métrica no aplica a esta plataforma o no se midió; el
        # dashboard lo pinta como guion, no como 0.
        "likes": m["likes"],
        "shares": m["shares"],
        "comments_count": m["comments_count"],
        "saves": m["saves"],
        "views": m["views"],
        "post_reach": m["post_reach"],
        "reach_source": m["reach_source"],
        "interactions": m["interactions"],
        "interaction_rate": m["interaction_rate"],
    } for m in mentions]

    quejas = [f for f in filas if f["is_complaint"]]
    # Bloque 7: el criterio de orden depende de qué alcance tiene la queja
    # — nunca se usa post_reach (visibilidad heredada del post) para
    # rankear: es constante entre todos los comentarios del mismo post, así
    # que ordenaría posts, no quejas, y no es comparable con el alcance
    # propio de TikTok. Dos grupos, con la métrica de orden visible en cada
    # card (ver template.html):
    #   with_own_reach:    tiene alcance PROPIO (hoy: solo TikTok) — ordena
    #                       por views. Es el único caso donde "cuánta gente
    #                       vio ESTO" es una cifra que la mención posee.
    #   without_own_reach: sin alcance propio (incluye TODO Instagram, que
    #                       solo tiene post_reach heredado, y cualquier fila
    #                       sin ningún dato de alcance) — ordena por
    #                       interacciones. post_reach viaja en el payload de
    #                       cada fila como CONTEXTO ("dónde apareció"), el
    #                       template lo muestra pero nunca lo usa para
    #                       ordenar ni para comparar contra el otro grupo.
    top_complaints = {
        "with_own_reach": sorted(
            [f for f in quejas if f["views"] is not None],
            key=lambda f: (f["views"], f["interactions"] or 0),
            reverse=True,
        )[:20],
        "without_own_reach": sorted(
            [f for f in quejas if f["views"] is None],
            key=lambda f: f["interactions"] or 0,
            reverse=True,
        )[:20],
    }

    # ── Calidad de datos
    por_plataforma = collections.Counter(m["platform"] for m in mentions)
    cobertura_mes = collections.Counter(m["published_at"][:7] for m in dated)

    # Cobertura por métrica y plataforma (Tarea 4, bloque 8): cuántas voces
    # de CADA plataforma tienen dato real (no None) en cada métrica. Mismo
    # universo que el resto del reporte (voces colapsadas, dentro de la
    # ventana) para que el número reconcilie con lo que ve el lector en los
    # demás bloques — no el conteo crudo de filas antes de colapsar.
    metric_coverage = {}
    for platform in PLATFORMS:
        voces_plat = [m for m in mentions if m["platform"] == platform]
        if not voces_plat:
            continue
        metric_coverage[platform] = {
            "total": len(voces_plat),
            **{
                metric: sum(1 for m in voces_plat if m[metric] is not None)
                for metric in ENGAGEMENT_METRICS
            },
        }

    # filtered_count se recalcula sobre el archivo/lote completo en cada corrida
    # de seed/scraping, aunque upsert_mentions deduplique lo ya visto. No hay
    # forma de deduplicar los descartes entre corridas (no se persisten), así
    # que un acumulado histórico sería una cifra inventada. Reportamos solo la
    # última corrida que terminó, etiquetada como tal — no un total.
    #
    # Acotada por marca cuando build_payload() se llamó con una: `runs` no
    # se filtra por defecto en la query, así que un payload de LATAM sin
    # esto reportaría la última corrida de AVIANCA (marca distinta) como si
    # fuera la suya — filtered_last_run, short_text_last_run y last_run_mode
    # quedarían mintiendo sobre datos de la otra marca. Sin `brand` (vista
    # combinada) se mantiene el comportamiento histórico: la última corrida
    # de cualquier marca.
    if brand is not None:
        last_run = conn.execute(
            "SELECT * FROM runs WHERE finished_at IS NOT NULL AND brand = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (brand,),
        ).fetchone()
    else:
        last_run = conn.execute(
            "SELECT * FROM runs WHERE finished_at IS NOT NULL "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    last_run = dict(last_run) if last_run else None

    data_quality = {
        "total": total,
        "unique_voices": total,
        "collapsed_repeats": collapsed_repeats,
        "unknown_date": sum(1 for m in mentions if m["date_confidence"] == "unknown"),
        "unclassified": sum(1 for m in mentions
                            if m["classification_status"] == "unclassified"),
        "filtered_last_run": (last_run["filtered_count"] or 0) if last_run else 0,
        "short_text_last_run": (last_run["short_text_count"] or 0) if last_run else 0,
        "last_run_mode": last_run["mode"] if last_run else None,
        "last_run_at": last_run["finished_at"] if last_run else None,
        "by_platform": dict(por_plataforma),
        "by_month": dict(sorted(cobertura_mes.items())),
        "missing_sources": ["twitter"],
        # Menciones (crudas, antes de colapsar) que quedaron fuera de la
        # ventana de reporte — ver docstring del módulo. Reales, en la DB,
        # pero fuera del análisis.
        "outside_window": outside_window,
        "window_start": REPORT_WINDOW_START,
        # Tarea 3 (relevancia social): menciones de TikTok, dentro de la
        # ventana de reporte, que exclusion_reason marca como resultado de
        # hashtag sin relación real con la marca (ver docstring del
        # módulo). Reales, en la DB, auditables — fuera del análisis por
        # la misma razón que outside_window: no borradas, solo no
        # contadas. `_reasons` desglosa el motivo tal cual lo reporta
        # is_relevant() ("sin_keyword", "sin_contexto_aeronautico").
        "excluded_irrelevant": excluded_irrelevant,
        "excluded_irrelevant_reasons": excluded_irrelevant_reasons,
        # Cambio 1 (retiro del canal web): menciones platform='web', dentro
        # de la ventana de reporte, que pipeline/web_channel_retirement.py
        # marcó con exclusion_reason=config.WEB_CHANNEL_RETIREMENT_REASON —
        # decisión de política (71 menciones web entre las dos marcas
        # producían solo 2 quejas reales; el resto, agregadores de vuelos y
        # ruido no relacionado), no una evaluación caso por caso como
        # excluded_irrelevant. Reales, en la DB, auditables — fuera del
        # análisis por la misma razón que las demás exclusiones.
        "excluded_web_retired": excluded_web_retired,
        # Tarea 4: qué métricas de engagement hay y cuáles no, por
        # plataforma, con conteo de filas — para que nadie saque
        # conclusiones de "shares" sin saber cuántas filas lo cubren.
        "metric_coverage": metric_coverage,
        # Declaración aparte de si la métrica APLICA conceptualmente a la
        # plataforma (ver METRIC_APPLIES) — el dashboard la usa para decir
        # "no aplica" (nunca va a tener el dato) en vez de "0 de N" (aplica
        # pero, hoy, cero filas lo tienen medido). Sin esto, metric_coverage
        # por sí solo no puede distinguir esos dos casos honestamente.
        "metric_applies": METRIC_APPLIES,
    }

    # Qué marca(s) representa este payload — para que la plantilla pueda
    # titularse sola (título, encabezado, color) sin adivinar a partir de
    # los datos. Con `brand` explícito, la identidad es esa marca aunque
    # hoy no tenga ni una mención (ver LATAM: el filtro fue explícito, el
    # nombre no depende de que haya datos). Sin filtro (vista combinada),
    # `names` refleja las marcas que de verdad aparecen en lo que se
    # devolvió — puede ser una sola si por ahora solo hay datos de una.
    brand_names = [brand] if brand is not None else sorted(
        {m["brand"] for m in mentions if m.get("brand")}
    )

    return {
        "brand": {"filter": brand, "names": brand_names},
        "kpis": kpis,
        "timeline": timeline,
        "drivers": drivers,
        "driver_by_platform": driver_by_platform,
        "driver_trend": driver_trend,
        "sentiment": {
            "counts": sent_counts,
            "pct": sent_pct,
            "classified_count": n_classified,
            # Promedio de probabilidades del clasificador — se conserva por
            # si sirve para otro análisis, pero el dashboard NO lo muestra:
            # "41,3% positivo" como promedio no significa "41,3% de las
            # menciones son positivas", que es lo que cualquiera asume al
            # leerlo (Cambio 2).
            "avg_probabilities": {
                "positive": round(avg_pos * 100, 1),
                "negative": round(avg_neg * 100, 1),
                "neutral": round(avg_neu * 100, 1),
            },
        },
        "emotions": emotions,
        "mentions": filas,
        "top_complaints": top_complaints,
        "data_quality": data_quality,
    }
