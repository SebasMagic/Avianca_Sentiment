"""
Capa de persistencia. Único módulo que toca SQLite.

Dedup por fingerprint (hash del contenido ya normalizado), no por
constraint sobre source_url — dos comentarios distintos pueden vivir
en la misma URL.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH, DEFAULT_BRAND

# Literal SQL del default de marca, usado tanto en SCHEMA como en las
# migraciones ALTER TABLE (que no admiten `?` para el DEFAULT de una
# columna). Comillas simples escapadas por si algún día DEFAULT_BRAND las
# trae — hoy no las trae, pero mejor no asumirlo en SQL interpolado.
_DEFAULT_BRAND_SQL = DEFAULT_BRAND.replace("'", "''")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS mentions (
    id                    TEXT PRIMARY KEY,
    fingerprint           TEXT NOT NULL UNIQUE,
    brand                 TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}',
    platform              TEXT NOT NULL,
    source_url            TEXT,
    text                  TEXT NOT NULL,
    author                TEXT,
    source_account        TEXT,
    published_at          TEXT,
    date_confidence       TEXT NOT NULL,
    country               TEXT,
    likes                 INTEGER DEFAULT 0,
    shares                INTEGER DEFAULT 0,
    comments_count        INTEGER DEFAULT 0,
    saves                 INTEGER,
    views                 INTEGER,
    reach_source          TEXT,
    sentiment_positive    REAL,
    sentiment_negative    REAL,
    sentiment_neutral     REAL,
    emotion               TEXT,
    is_complaint          INTEGER DEFAULT 0,
    complaint_driver      TEXT,
    classification_status TEXT NOT NULL,
    raw                   TEXT,
    fetched_at            TEXT,
    run_id                TEXT,
    exclusion_reason      TEXT,
    rating                INTEGER
);

CREATE INDEX IF NOT EXISTS idx_mentions_published ON mentions(published_at);
CREATE INDEX IF NOT EXISTS idx_mentions_platform  ON mentions(platform);
CREATE INDEX IF NOT EXISTS idx_mentions_complaint ON mentions(is_complaint);
CREATE INDEX IF NOT EXISTS idx_mentions_driver    ON mentions(complaint_driver);
CREATE INDEX IF NOT EXISTS idx_mentions_status    ON mentions(classification_status);

CREATE TABLE IF NOT EXISTS runs (
    id                TEXT PRIMARY KEY,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    mode              TEXT NOT NULL,
    since             TEXT,
    brand             TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}',
    raw_count         INTEGER DEFAULT 0,
    filtered_count    INTEGER DEFAULT 0,
    inserted_count    INTEGER DEFAULT 0,
    duplicate_count   INTEGER DEFAULT 0,
    short_text_count  INTEGER DEFAULT 0,
    notes             TEXT
);

-- ── Visibilidad de marca en respuestas de IA ────────────────────────────
--
-- Esto NO son menciones (no son comentarios ni reseñas de un usuario real,
-- no tienen autor ni texto libre publicado por alguien) — son MÉTRICAS por
-- marca/modelo/fecha de captura, y viven en tablas propias, nunca como
-- filas de `mentions`. `captured_at` (no `published_at`) es la fecha que
-- importa acá: cuándo NOSOTROS medimos el dato, para poder comparar
-- corridas en el tiempo — ver dashboard/ai_visibility_aggregate.py.
--
-- Cinco tablas, una por forma de dato (mismo criterio que separar
-- `mentions` de `runs`: cada una tiene su propia grilla de columnas, no
-- tiene sentido forzarlas a un esquema común):
--
--   ai_brand_metrics:          mentions + ai_search_volume agregados de
--                               una marca en respuestas de IA — endpoint
--                               target_metrics (una marca) o
--                               multi_target_metrics (todas a la vez,
--                               source_endpoint lo distingue).
--   ai_brand_sources:          qué dominios citan los modelos al hablar de
--                               la marca (aggregated_metrics.sources_domain
--                               de esos mismos endpoints) — que aparezca el
--                               dominio de un competidor entre las fuentes
--                               es el hallazgo que motivó este bloque
--                               (is_competitor_domain).
--   ai_prompt_responses:       la respuesta COMPLETA de un modelo a UN
--                               prompt propio (config.get_ai_prompts) — el
--                               texto real, no solo un número.
--   ai_prompt_brand_mentions:  qué marca(s) se evaluaron contra esa
--                               respuesta y con qué resultado (aparece,
--                               posición, sentimiento) — separada de
--                               ai_prompt_responses porque un prompt de
--                               categoría (sin marca propia) se evalúa
--                               contra VARIAS marcas a la vez sobre el
--                               mismo texto de respuesta; no tiene sentido
--                               duplicar la respuesta por cada marca.
--   ai_search_mention_examples: ejemplos reales de pregunta+respuesta ya
--                               indexados por DataForSEO (Google AI
--                               Overview u otro `platform`) que mencionan
--                               la marca — endpoint search_mentions;
--                               complementa ai_prompt_responses con
--                               preguntas que la gente YA le hace a la IA,
--                               no solo las que nosotros diseñamos.
--
-- Y una tabla de share of voice en búsqueda (Tarea 3, bloque aparte):
--
--   search_share_of_voice:     volumen de búsqueda real por keyword
--                               "marca + término" (p.ej. "avianca demanda"),
--                               con su intención (problema/comercial) y motor
--                               (google_ads / ai_search) — endpoints
--                               keywords_data/google_ads/search_volume y
--                               ai_optimization/ai_keyword_data/
--                               keywords_search_volume.
--
-- Todas idempotentes vía CREATE TABLE IF NOT EXISTS — tablas nuevas, no
-- hace falta ALTER TABLE (eso solo aplica a columnas nuevas sobre tablas
-- YA existentes, ver _migrate). `run_id` en todas referencia `runs.id`
-- sin FK declarada a propósito (mismo estilo que `mentions.run_id`) —
-- SQLite no aplica FKs por defecto y esto es solo trazabilidad, no
-- integridad referencial estricta.

CREATE TABLE IF NOT EXISTS ai_brand_metrics (
    id                TEXT PRIMARY KEY,
    brand             TEXT NOT NULL,
    captured_at       TEXT NOT NULL,
    domain            TEXT NOT NULL,
    platform          TEXT NOT NULL,
    mentions          INTEGER NOT NULL,
    ai_search_volume  INTEGER NOT NULL,
    source_endpoint   TEXT NOT NULL,
    raw               TEXT,
    run_id            TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_brand_metrics_brand ON ai_brand_metrics(brand);
CREATE INDEX IF NOT EXISTS idx_ai_brand_metrics_captured ON ai_brand_metrics(captured_at);

CREATE TABLE IF NOT EXISTS ai_brand_sources (
    id                     TEXT PRIMARY KEY,
    brand                  TEXT NOT NULL,
    captured_at            TEXT NOT NULL,
    cited_domain           TEXT NOT NULL,
    mentions               INTEGER NOT NULL,
    ai_search_volume       INTEGER NOT NULL,
    is_own_domain          INTEGER NOT NULL DEFAULT 0,
    is_competitor_domain   INTEGER NOT NULL DEFAULT 0,
    source_endpoint        TEXT NOT NULL,
    run_id                 TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_brand_sources_brand ON ai_brand_sources(brand);
CREATE INDEX IF NOT EXISTS idx_ai_brand_sources_captured ON ai_brand_sources(captured_at);

CREATE TABLE IF NOT EXISTS ai_prompt_responses (
    id                TEXT PRIMARY KEY,
    captured_at       TEXT NOT NULL,
    platform          TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt            TEXT NOT NULL,
    prompt_scope      TEXT NOT NULL,
    subject_brand     TEXT,
    response_text     TEXT NOT NULL,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    money_spent       REAL,
    raw               TEXT,
    run_id            TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_prompt_responses_captured ON ai_prompt_responses(captured_at);

CREATE TABLE IF NOT EXISTS ai_prompt_brand_mentions (
    id                     TEXT PRIMARY KEY,
    response_id            TEXT NOT NULL,
    brand                  TEXT NOT NULL,
    appears                INTEGER NOT NULL DEFAULT 0,
    position               INTEGER,
    sentiment_positive     REAL,
    sentiment_negative     REAL,
    sentiment_neutral      REAL,
    emotion                TEXT,
    classification_status  TEXT NOT NULL DEFAULT 'unclassified'
);

CREATE INDEX IF NOT EXISTS idx_ai_prompt_brand_mentions_response ON ai_prompt_brand_mentions(response_id);
CREATE INDEX IF NOT EXISTS idx_ai_prompt_brand_mentions_brand ON ai_prompt_brand_mentions(brand);

CREATE TABLE IF NOT EXISTS ai_search_mention_examples (
    id                 TEXT PRIMARY KEY,
    brand              TEXT NOT NULL,
    captured_at        TEXT NOT NULL,
    platform           TEXT,
    question           TEXT,
    answer             TEXT,
    ai_search_volume   INTEGER,
    top_source_domain  TEXT,
    top_source_url     TEXT,
    raw                TEXT,
    run_id             TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_search_mention_examples_brand ON ai_search_mention_examples(brand);

CREATE TABLE IF NOT EXISTS search_share_of_voice (
    id             TEXT PRIMARY KEY,
    brand          TEXT NOT NULL,
    captured_at    TEXT NOT NULL,
    keyword        TEXT NOT NULL,
    intent         TEXT NOT NULL,
    engine         TEXT NOT NULL,
    search_volume  INTEGER,
    raw            TEXT,
    run_id         TEXT
);

CREATE INDEX IF NOT EXISTS idx_search_share_of_voice_brand ON search_share_of_voice(brand);
"""

_FIELDS = [
    "id", "fingerprint", "brand", "platform", "source_url", "text", "author",
    "source_account", "published_at", "date_confidence", "country", "likes", "shares",
    "comments_count", "saves", "views", "reach_source",
    "sentiment_positive", "sentiment_negative",
    "sentiment_neutral", "emotion", "is_complaint", "complaint_driver",
    "classification_status", "raw", "fetched_at", "run_id", "rating",
]

# Columnas de engagement/alcance que update_engagement() tiene permitido tocar.
# Allowlist fija — nunca se interpola un nombre de columna que no venga de aquí,
# así el UPDATE dinámico no puede ejecutar SQL arbitrario a partir del dict que
# le pase el llamador.
_ENGAGEMENT_FIELDS = {"likes", "shares", "comments_count", "saves", "views", "reach_source"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Migraciones aditivas sobre bases YA existentes. Nunca destructivo:
    solo agrega columnas que falten (ALTER TABLE ... ADD COLUMN), nunca
    borra ni recrea tablas. Idempotente: si la columna ya existe, no hace
    nada. data/avianca.db tiene datos reales de scraping pagado — una
    migración destructiva no es aceptable.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "short_text_count" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN short_text_count INTEGER DEFAULT 0")
        conn.commit()
    if "brand" not in cols:
        conn.execute(
            f"ALTER TABLE runs ADD COLUMN brand TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}'"
        )
        conn.commit()

    # saves/views/reach_source (desglose de engagement — ver
    # pipeline/engagement_enrichment.py): sin DEFAULT, quedan NULL en filas
    # viejas. NULL es correcto aquí — "no medido todavía", no "cero".
    mention_cols = {row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()}
    for col, coltype in (("saves", "INTEGER"), ("views", "INTEGER"), ("reach_source", "TEXT")):
        if col not in mention_cols:
            conn.execute(f"ALTER TABLE mentions ADD COLUMN {col} {coltype}")
            conn.commit()

    if "brand" not in mention_cols:
        _add_brand_column_and_refingerprint(conn)

    # source_account: cuenta/perfil de Instagram (u otra plataforma, si
    # algún día aplica) que PUBLICÓ EL POST del que salió la mención — no
    # confundir con `author`, que es quien escribió el comentario. Sin
    # DEFAULT, queda NULL en filas viejas: no se inventa de qué cuenta
    # salió un post ya scrapeado antes de que este campo existiera: la
    # única fuente honesta es el dato real de Fase 1 del scraper
    # (ver scrapers/apify_instagram.py), no una suposición retroactiva.
    if "source_account" not in mention_cols:
        conn.execute("ALTER TABLE mentions ADD COLUMN source_account TEXT")
        conn.commit()

    # exclusion_reason: marca una mención social de HASHTAG (hoy: TikTok)
    # como excluida de las agregaciones del dashboard sin borrar la fila —
    # ver pipeline/relevance.py (Tarea 1/2 de la corrección de relevancia
    # social) y pipeline/social_relevance_backfill.py (Tarea 3, aplica la
    # regla retroactivamente a lo que ya estaba guardado). NULL = incluida
    # (default para toda fila nueva o vieja); con texto = la razón de
    # descarte ("sin_keyword", "sin_contexto_aeronautico" — las mismas que
    # devuelve is_relevant()), igual que ya se hace con el filtro web.
    #
    # Reversible por diseño: es una sola columna, nunca una fila borrada —
    # si la regla resulta mal calibrada, corregirla y re-correr el backfill
    # deja la columna en NULL de nuevo para las filas que ya no aplican.
    # dashboard/aggregate.py la trata igual que la ventana de reporte
    # (config.REPORT_WINDOW_START): la fila sigue en la DB, auditable, pero
    # ningún bloque del dashboard la cuenta.
    if "exclusion_reason" not in mention_cols:
        conn.execute("ALTER TABLE mentions ADD COLUMN exclusion_reason TEXT")
        conn.commit()

    # rating: estrella (1-5) de una reseña (platform='resena', ver
    # scrapers/dataforseo_reviews.py) — dato que no existía en el schema
    # hasta la incorporación de prensa/reseñas. Sin DEFAULT: NULL para
    # toda fila que no sea una reseña (instagram, tiktok, prensa) y para
    # las reseñas de corridas futuras que aún no se clasificaron — nunca
    # se inventa una estrella para lo que no la tiene.
    if "rating" not in mention_cols:
        conn.execute("ALTER TABLE mentions ADD COLUMN rating INTEGER")
        conn.commit()

    # Índice sobre brand — se crea acá y no dentro de SCHEMA porque en una
    # DB vieja la columna todavía no existe cuando SCHEMA corre (SCHEMA se
    # ejecuta antes que _migrate); para cuando se llega a esta línea,
    # `brand` ya existe siempre (recién agregada arriba, o ya estaba si la
    # DB es nueva).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_brand ON mentions(brand)")
    conn.commit()


def _add_brand_column_and_refingerprint(conn: sqlite3.Connection) -> None:
    """
    Multi-marca (Tarea 1): agrega `brand` a `mentions` con DEFAULT
    'Avianca' — correcto para las 1.261 filas existentes, todas de
    Avianca — y recalcula el fingerprint de cada una con la nueva firma
    fingerprint(brand, platform, source_url, author, text); antes era
    fingerprint(platform, source_url, author, text), sin marca.

    Recalcular es determinista y no debería colapsar ninguna fila: el
    fingerprint viejo ya era único por combinación
    (platform, source_url, author, text); el nuevo solo le antepone la
    marca (constante 'Avianca' para todas, en esta migración), así que la
    inyectividad se preserva. Aun así se verifica el conteo de filas y de
    fingerprints distintos antes y después, y se aborta la migración
    completa (se lanza, no se traga el error) si no coinciden — sobre
    datos ya pagados, mejor fallar ruidosamente que fusionar en silencio.
    """
    before_count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]

    conn.execute(
        f"ALTER TABLE mentions ADD COLUMN brand TEXT NOT NULL DEFAULT '{_DEFAULT_BRAND_SQL}'"
    )
    conn.commit()

    rows = conn.execute(
        "SELECT id, platform, source_url, author, text FROM mentions"
    ).fetchall()
    for row in rows:
        mid, platform, source_url, author, text = row[0], row[1], row[2], row[3], row[4]
        new_fp = fingerprint(DEFAULT_BRAND, platform, source_url, author, text)
        conn.execute("UPDATE mentions SET fingerprint = ? WHERE id = ?", (new_fp, mid))
    conn.commit()

    after_count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
    distinct_fp = conn.execute("SELECT COUNT(DISTINCT fingerprint) FROM mentions").fetchone()[0]

    if after_count != before_count:
        raise RuntimeError(
            "Migración de brand/fingerprint abortada: "
            f"filas antes={before_count} después={after_count} — no coinciden."
        )
    if distinct_fp != after_count:
        raise RuntimeError(
            "Migración de brand/fingerprint abortada: "
            f"{after_count} filas pero solo {distinct_fp} fingerprints distintos "
            "— el recálculo habría colapsado filas."
        )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def fingerprint(brand: str, platform: str, source_url: str, author: str | None, text: str) -> str:
    """
    Hash SHA256 del contenido completo (brand|platform|url|author|text íntegro).

    Se hashea el TEXTO COMPLETO sin truncar para evitar colisiones falsas.
    Dos comentarios genuinamente distintos que comparten un prefijo largo
    pueden coexistir en la misma URL — el dedup por fingerprint debe
    distinguirlos correctamente.

    El autor está incluido en el fingerprint para discriminar personas distintas:
    si dos autores distintos escriben lo mismo en la misma URL, son dos menciones
    diferentes. Esto evita falsos positivos en redes donde la URL es constante
    (ej. Instagram scrape usa una URL genérica). Un mismo autor repitiendo texto
    idéntico SÍ se deduplica correctamente (re-scrape).

    La marca también está incluida: dos marcas pueden tener menciones
    legítimamente idénticas (una nota de prensa que nombra a ambas) y no
    deben deduplicarse entre sí — cada marca vive en su propio espacio de
    fingerprints.

    Diseño: un duplicado falso es una fila auditable; una fusión falsa
    es pérdida irrecuperable de datos. La asimetría decide: hashea completo.
    """
    base = f"{brand}|{platform}|{source_url or ''}|{author or ''}|{text or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def start_run(conn: sqlite3.Connection, mode: str, since: str | None,
              brand: str = DEFAULT_BRAND) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (id, started_at, mode, since, brand) VALUES (?, ?, ?, ?, ?)",
        (run_id, _now(), mode, since, brand),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id, raw_count, filtered_count,
               inserted_count, duplicate_count, notes="",
               short_text_count=0) -> None:
    conn.execute(
        """UPDATE runs SET finished_at = ?, raw_count = ?, filtered_count = ?,
                           inserted_count = ?, duplicate_count = ?,
                           short_text_count = ?, notes = ?
           WHERE id = ?""",
        (_now(), raw_count, filtered_count, inserted_count,
         duplicate_count, short_text_count, notes, run_id),
    )
    conn.commit()


def upsert_mentions(conn, mentions: list[dict], run_id: str) -> tuple[int, int]:
    """
    Inserta menciones nuevas. Las que ya existen (mismo fingerprint) se
    ignoran por completo — no se sobrescriben, para preservar run_id y
    fetched_at de la primera vez que se vieron.

    Devuelve (insertadas, duplicadas).
    """
    inserted = 0
    duplicates = 0

    for m in mentions:
        brand = m.get("brand") or DEFAULT_BRAND
        fp = fingerprint(brand, m["platform"], m.get("source_url", ""), m.get("author"), m["text"])
        row = {
            **{f: m.get(f) for f in _FIELDS},
            "id": m.get("id") or str(uuid.uuid4()),
            "brand": brand,
            "fingerprint": fp,
            "raw": json.dumps(m.get("raw") or {}, ensure_ascii=False),
            "run_id": run_id,
            "is_complaint": int(bool(m.get("is_complaint", 0))),
            "classification_status": m.get("classification_status", "unclassified"),
        }
        placeholders = ", ".join("?" for _ in _FIELDS)
        cur = conn.execute(
            f"INSERT OR IGNORE INTO mentions ({', '.join(_FIELDS)}) "
            f"VALUES ({placeholders})",
            [row[f] for f in _FIELDS],
        )
        if cur.rowcount:
            inserted += 1
        else:
            duplicates += 1

    conn.commit()
    return inserted, duplicates


def _to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("raw"):
        try:
            d["raw"] = json.loads(d["raw"])
        except (ValueError, TypeError):
            d["raw"] = {}
    return d


def pending_classification(conn, brand: str | None = None) -> list[dict]:
    """
    Menciones sin clasificar. `brand` es opcional: sin él, devuelve las
    pendientes de todas las marcas (comportamiento histórico); pasándolo,
    lo acota a una sola — así una corrida de LATAM no reintenta clasificar
    con el prompt de LATAM las pendientes que dejó una corrida de Avianca.
    """
    if brand is None:
        rows = conn.execute(
            "SELECT * FROM mentions WHERE classification_status = 'unclassified'"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM mentions WHERE classification_status = 'unclassified' AND brand = ?",
            (brand,),
        ).fetchall()
    return [_to_dict(r) for r in rows]


def update_classification(conn, mention_id: str, result: dict) -> None:
    conn.execute(
        """UPDATE mentions
           SET sentiment_positive = ?, sentiment_negative = ?,
               sentiment_neutral = ?, emotion = ?, is_complaint = ?,
               complaint_driver = ?, classification_status = 'classified'
           WHERE id = ?""",
        (
            result["sentiment_positive"],
            result["sentiment_negative"],
            result["sentiment_neutral"],
            result["emotion"],
            int(bool(result["is_complaint"])),
            result.get("complaint_driver"),
            mention_id,
        ),
    )
    conn.commit()


def update_engagement(conn, mention_id: str, fields: dict) -> None:
    """
    Actualiza columnas de engagement/alcance (likes, shares, comments_count,
    saves, views, reach_source) de una mención YA existente. No inserta filas,
    no toca clasificación ni ningún otro campo — usado por el enriquecimiento
    retroactivo (pipeline/engagement_enrichment.py, backfill de alcance de
    Instagram) para corregir esas columnas desde datos ya pagados.

    `fields` puede traer solo un subconjunto (p.ej. solo views+reach_source);
    las claves fuera de _ENGAGEMENT_FIELDS se ignoran en vez de fallar, para
    que el llamador pueda pasar un dict con más contexto sin filtrar antes.
    Solo se actualizan columnas de la allowlist fija _ENGAGEMENT_FIELDS —
    nunca se interpola un nombre de columna ajeno al dict.
    """
    cols = [c for c in fields if c in _ENGAGEMENT_FIELDS]
    if not cols:
        return
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(
        f"UPDATE mentions SET {set_clause} WHERE id = ?",
        [fields[c] for c in cols] + [mention_id],
    )
    conn.commit()


def update_source_account(conn, mention_id: str, source_account: str | None) -> None:
    """
    Actualiza SOLO `source_account` de una mención YA existente. No
    inserta filas, no toca ninguna otra columna — usado por el backfill
    retroactivo (pipeline/source_account_backfill.py) para poblar la
    cuenta de origen de comentarios de Instagram que se guardaron ANTES
    de que source_account existiera (ver Tarea 1, migración aditiva en
    _migrate — esas filas quedan NULL hasta que algo las corrija con un
    dato real, nunca con una suposición).
    """
    conn.execute(
        "UPDATE mentions SET source_account = ? WHERE id = ?",
        (source_account, mention_id),
    )
    conn.commit()


def set_exclusion_reason(conn, mention_id: str, reason: str | None) -> None:
    """
    Marca (o desmarca) una mención como excluida de las agregaciones del
    dashboard sin borrar la fila — usado por el backfill retroactivo
    (pipeline/social_relevance_backfill.py, Tarea 3) para aplicar el
    filtro de relevancia de hashtag (pipeline/relevance.py) a menciones
    de TikTok que ya estaban en la DB antes de que ese filtro existiera.

    `reason` es la razón de descarte que devuelve is_relevant() (p.ej.
    "sin_contexto_aeronautico") o None para reincluir una fila — la
    exclusión es reversible por diseño: si la regla resulta mal calibrada,
    corregirla y volver a correr el backfill deja `exclusion_reason` en
    NULL de nuevo para las filas que ya no aplican, sin perder ningún dato
    (nunca se borra una fila; ver docstring de _migrate).
    """
    conn.execute(
        "UPDATE mentions SET exclusion_reason = ? WHERE id = ?",
        (reason, mention_id),
    )
    conn.commit()


def all_mentions(conn, brand: str | None = None) -> list[dict]:
    """
    Todas las menciones, o solo las de `brand` si se pasa uno — el
    dashboard y el export de Excel quieren la vista de una sola marca a
    la vez, sin dejar de poder pedir todo junto cuando haga falta.
    """
    if brand is None:
        rows = conn.execute("SELECT * FROM mentions ORDER BY published_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM mentions WHERE brand = ? ORDER BY published_at DESC", (brand,)
        ).fetchall()
    return [_to_dict(r) for r in rows]


def last_completed_run_started_at(conn) -> str | None:
    """
    `started_at` (ISO 8601) de la última corrida que TERMINÓ
    (finished_at IS NOT NULL), o None si no hay ninguna.

    Se usa para calcular el `since` incremental de la corrida `weekly`:
    apoyarse en cuándo arrancó la última corrida real (en vez de un
    rolling fijo de 7 días) evita abrir huecos si una semana se salta.
    Corridas en curso o abortadas (sin finished_at) no cuentan.
    """
    row = conn.execute(
        "SELECT started_at FROM runs WHERE finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row["started_at"] if row else None


# ── Visibilidad de marca en respuestas de IA ─────────────────────────────
#
# Las funciones de esta sección solo INSERTAN (no hay dedup por
# fingerprint: cada captura es una fotografía con su propio `captured_at`,
# y dos capturas del mismo dato en fechas distintas son dos filas válidas
# a propósito — es justamente lo que permite comparar corridas en el
# tiempo, ver docstring de SCHEMA arriba). `run_id` liga cada fila a la
# corrida de `runs` que la produjo (start_run/finish_run con
# mode="ai_visibility" — ver pipeline/ai_visibility.py), mismo patrón que
# ya usa `mentions.run_id`.


def insert_ai_brand_metrics(conn, rows: list[dict], run_id: str | None) -> int:
    """
    `rows`: [{"brand", "captured_at", "domain", "platform", "mentions",
    "ai_search_volume", "source_endpoint", "raw"}, ...] — ver
    scrapers/dataforseo_ai_visibility.py. Devuelve cuántas filas se
    insertaron.
    """
    for r in rows:
        conn.execute(
            """INSERT INTO ai_brand_metrics
               (id, brand, captured_at, domain, platform, mentions,
                ai_search_volume, source_endpoint, raw, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), r["brand"], r["captured_at"], r["domain"],
                r["platform"], r["mentions"], r["ai_search_volume"],
                r["source_endpoint"], json.dumps(r.get("raw") or {}, ensure_ascii=False),
                run_id,
            ),
        )
    conn.commit()
    return len(rows)


def insert_ai_brand_sources(conn, rows: list[dict], run_id: str | None) -> int:
    """
    `rows`: [{"brand", "captured_at", "cited_domain", "mentions",
    "ai_search_volume", "is_own_domain", "is_competitor_domain",
    "source_endpoint"}, ...]. Devuelve cuántas filas se insertaron.
    """
    for r in rows:
        conn.execute(
            """INSERT INTO ai_brand_sources
               (id, brand, captured_at, cited_domain, mentions,
                ai_search_volume, is_own_domain, is_competitor_domain,
                source_endpoint, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), r["brand"], r["captured_at"], r["cited_domain"],
                r["mentions"], r["ai_search_volume"],
                int(bool(r.get("is_own_domain", 0))),
                int(bool(r.get("is_competitor_domain", 0))),
                r["source_endpoint"], run_id,
            ),
        )
    conn.commit()
    return len(rows)


def insert_ai_prompt_response(conn, response: dict, mentions: list[dict],
                               run_id: str | None) -> str:
    """
    Inserta UNA respuesta de modelo (`response`: {"captured_at",
    "platform", "model", "prompt", "prompt_scope", "subject_brand",
    "response_text", "input_tokens", "output_tokens", "money_spent",
    "raw"}) y sus extracciones por marca (`mentions`: [{"brand",
    "appears", "position", "sentiment_positive", "sentiment_negative",
    "sentiment_neutral", "emotion", "classification_status"}, ...] —
    típicamente una por cada marca de config.BRANDS evaluada contra este
    texto). Devuelve el id de la respuesta insertada, para quien necesite
    referenciarla.
    """
    response_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO ai_prompt_responses
           (id, captured_at, platform, model, prompt, prompt_scope,
            subject_brand, response_text, input_tokens, output_tokens,
            money_spent, raw, run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            response_id, response["captured_at"], response["platform"],
            response["model"], response["prompt"], response["prompt_scope"],
            response.get("subject_brand"), response["response_text"],
            response.get("input_tokens"), response.get("output_tokens"),
            response.get("money_spent"),
            json.dumps(response.get("raw") or {}, ensure_ascii=False), run_id,
        ),
    )
    for m in mentions:
        conn.execute(
            """INSERT INTO ai_prompt_brand_mentions
               (id, response_id, brand, appears, position,
                sentiment_positive, sentiment_negative, sentiment_neutral,
                emotion, classification_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), response_id, m["brand"],
                int(bool(m.get("appears", 0))), m.get("position"),
                m.get("sentiment_positive"), m.get("sentiment_negative"),
                m.get("sentiment_neutral"), m.get("emotion"),
                m.get("classification_status", "unclassified"),
            ),
        )
    conn.commit()
    return response_id


def insert_ai_search_mention_examples(conn, rows: list[dict], run_id: str | None) -> int:
    """
    `rows`: [{"brand", "captured_at", "platform", "question", "answer",
    "ai_search_volume", "top_source_domain", "top_source_url", "raw"},
    ...]. Devuelve cuántas filas se insertaron.
    """
    for r in rows:
        conn.execute(
            """INSERT INTO ai_search_mention_examples
               (id, brand, captured_at, platform, question, answer,
                ai_search_volume, top_source_domain, top_source_url, raw, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), r["brand"], r["captured_at"], r.get("platform"),
                r.get("question"), r.get("answer"), r.get("ai_search_volume"),
                r.get("top_source_domain"), r.get("top_source_url"),
                json.dumps(r.get("raw") or {}, ensure_ascii=False), run_id,
            ),
        )
    conn.commit()
    return len(rows)


def insert_search_share_of_voice(conn, rows: list[dict], run_id: str | None) -> int:
    """
    `rows`: [{"brand", "captured_at", "keyword", "intent", "engine",
    "search_volume", "raw"}, ...]. Devuelve cuántas filas se insertaron.
    """
    for r in rows:
        conn.execute(
            """INSERT INTO search_share_of_voice
               (id, brand, captured_at, keyword, intent, engine,
                search_volume, raw, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), r["brand"], r["captured_at"], r["keyword"],
                r["intent"], r["engine"], r.get("search_volume"),
                json.dumps(r.get("raw") or {}, ensure_ascii=False), run_id,
            ),
        )
    conn.commit()
    return len(rows)


# ── Lecturas para el dashboard (dashboard/ai_visibility_aggregate.py) ────
#
# Todas devuelven TODAS las filas de la marca (sin filtrar a "la última
# corrida") — la agregación decide cómo recortar a la captura más
# reciente (MAX(captured_at)) o cómo armar una serie en el tiempo; esta
# capa solo lee, no decide qué es "vigente".

def ai_brand_metrics_for_brand(conn, brand: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ai_brand_metrics WHERE brand = ? ORDER BY captured_at DESC",
        (brand,),
    ).fetchall()
    return [_to_dict(r) for r in rows]


def ai_brand_sources_for_brand(conn, brand: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ai_brand_sources WHERE brand = ? ORDER BY captured_at DESC",
        (brand,),
    ).fetchall()
    return [_to_dict(r) for r in rows]


def ai_prompt_responses_for_brand(conn, brand: str) -> list[dict]:
    """
    Respuestas donde `brand` fue una de las marcas evaluadas (prompts
    propios de esa marca, más los prompts de categoría, que se evalúan
    contra todas). Cada fila trae el texto completo de la respuesta más
    los campos de `ai_prompt_brand_mentions` para ESA marca (appears,
    position, sentiment, emotion) ya incorporados — un JOIN, no dos
    lecturas que el llamador tenga que cruzar a mano.
    """
    rows = conn.execute(
        """SELECT r.*, m.appears, m.position, m.sentiment_positive,
                  m.sentiment_negative, m.sentiment_neutral, m.emotion,
                  m.classification_status
           FROM ai_prompt_responses r
           JOIN ai_prompt_brand_mentions m ON m.response_id = r.id
           WHERE m.brand = ?
           ORDER BY r.captured_at DESC""",
        (brand,),
    ).fetchall()
    return [_to_dict(r) for r in rows]


def ai_search_mention_examples_for_brand(conn, brand: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ai_search_mention_examples WHERE brand = ? ORDER BY captured_at DESC",
        (brand,),
    ).fetchall()
    return [_to_dict(r) for r in rows]


def search_share_of_voice_for_brand(conn, brand: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM search_share_of_voice WHERE brand = ? ORDER BY captured_at DESC",
        (brand,),
    ).fetchall()
    return [_to_dict(r) for r in rows]


def latest_completed_run(conn, brand: str, mode: str) -> dict | None:
    """
    La corrida más reciente que TERMINÓ (finished_at IS NOT NULL) para
    `brand` y `mode` exactos, o None si no hay ninguna.

    Usado por dashboard/ai_visibility_aggregate.py para agrupar las filas
    de una misma captura: dentro de UNA corrida de
    pipeline.ai_visibility.run() (mode="ai_visibility"), cada prompt
    propio (scrapers/dataforseo_ai_prompts.py) recibe su propio
    `captured_at` — son varias llamadas HTTP secuenciales, no
    instantáneas — así que agrupar por igualdad exacta de `captured_at`
    no agruparía bien las filas de una misma corrida. `run_id` sí es
    constante para TODA una corrida (se genera una vez, al empezar) y por
    eso es el criterio correcto para "la captura más reciente".
    """
    row = conn.execute(
        "SELECT * FROM runs WHERE finished_at IS NOT NULL AND brand = ? AND mode = ? "
        "ORDER BY started_at DESC LIMIT 1",
        (brand, mode),
    ).fetchone()
    return dict(row) if row else None
