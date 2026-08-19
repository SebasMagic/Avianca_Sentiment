# Avianca Sentiment Monitor v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir el pipeline de social listening de Avianca en un sistema que acumula 4 meses de historia en SQLite local, clasifica cada queja por driver operativo, y genera un dashboard HTML autocontenido.

**Architecture:** `scrapers → normalizer → relevance → classifier → store/db (SQLite) → dashboard/build.py → HTML autocontenido`. Cero infraestructura remota: se elimina Supabase por completo. Cada módulo tiene una responsabilidad única y los módulos con lógica real (relevance, db, classifier, aggregate) son puros o mockeables, de modo que ningún test toca una API.

**Tech Stack:** Python 3.12 · SQLite (stdlib `sqlite3`) · pytest · requests · openpyxl · apify-client · DeepSeek API · Chart.js 4.4 (vendorizado)

**Spec:** [docs/superpowers/specs/2026-08-19-avianca-sentiment-4meses-design.md](../specs/2026-08-19-avianca-sentiment-4meses-design.md)

## Global Constraints

- **Python 3.12**, ya instalado en `C:\Users\sebas\AppData\Local\Programs\Python\Python312`.
- **Plataformas válidas:** `web`, `instagram`, `tiktok`. Twitter/X queda fuera de v2.
- **Drivers de queja (exactamente estos 9):** `equipaje`, `cancelacion`, `demora`, `atencion_cliente`, `cobros_tarifas`, `lifemiles`, `asientos_comida`, `reembolsos`, `otro`.
- **`date_confidence` (exactamente estos 3):** `exact`, `approx`, `unknown`.
- **`classification_status` (exactamente estos 2):** `classified`, `unclassified`.
- **Rango del backfill:** `2026-04-19` → `2026-08-19` (120 días).
- **Prohibido rellenar fechas ausentes.** Si no hay fecha de publicación, `published_at` queda `NULL` y `date_confidence = 'unknown'`. Nunca se sustituye por `fetched_at`.
- **Ningún test hace llamadas de red.** Todo lo que hable con una API se mockea con `unittest.mock.patch`.
- **La consola de Windows es cp1252.** Todo script que imprima acentos o emoji debe correrse con `PYTHONIOENCODING=utf-8`, y todo `open()` de archivos de texto debe pasar `encoding="utf-8"` explícito.
- **Motor LLM:** DeepSeek (`DEEPSEEK_API_KEY` ya existe en `.env`). Endpoint `https://api.deepseek.com/chat/completions`, modelo `deepseek-chat`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `config.py` | Constantes del proyecto: drivers, blacklist, stopwords, rutas, límites. Sin lógica. |
| `pipeline/relevance.py` | Decide si una mención web es sobre la aerolínea o es ruido. Función pura, sin red, sin DB. |
| `pipeline/normalizer.py` | Valida tipos, limpia texto, asigna `date_confidence`. No descarta por contenido. |
| `pipeline/classifier.py` | Único módulo que habla con DeepSeek. Sentiment + emoción + queja + driver. |
| `store/db.py` | Único módulo que toca SQLite. Schema, fingerprint, upsert idempotente, tracking de corridas, queries. |
| `store/seed_excel.py` | Importa el Excel v1 al schema nuevo. |
| `scrapers/*.py` | Dado un `since`, devuelven `list[dict]` en schema unificado. No clasifican ni filtran. |
| `dashboard/aggregate.py` | Lee la DB y produce el payload JSON del dashboard. Sin HTML, sin red. |
| `dashboard/build.py` | Inyecta el payload en la plantilla y escribe el HTML final. |
| `dashboard/template.html` | Plantilla visual con marcador `__DASHBOARD_DATA__`. |
| `main.py` | CLI y orquestación. Sin lógica de negocio. |

---

## Task 1: Andamiaje — git, pytest, config, estructura

**Files:**
- Create: `.gitignore`, `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`, `store/__init__.py`, `data/.gitkeep`
- Modify: `config.py`, `requirements.txt`

**Interfaces:**
- Consumes: nada
- Produces: `config.COMPLAINT_DRIVERS: list[str]`, `config.BLACKLIST_DOMAIN_ROOTS: set[str]`, `config.SPANISH_STOPWORDS: set[str]`, `config.DB_PATH: str`, `config.BACKFILL_SINCE: str`, `config.INSTAGRAM_POSTS_LIMIT: int`. Fixture `tmp_db` en `tests/conftest.py`.

- [ ] **Step 1: Inicializar git**

El proyecto no es un repo. Desde la raíz:

```bash
git init
git add -A
git commit -m "chore: snapshot del pipeline v1 antes de la migración a v2"
```

- [ ] **Step 2: Crear `.gitignore`**

```
__pycache__/
*.pyc
.env
data/*.db
*.xlsx
dashboard/avianca_dashboard_*.html
.pytest_cache/
```

- [ ] **Step 3: Crear `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -v
```

- [ ] **Step 4: Añadir pytest a `requirements.txt` y quitar lo de Supabase**

Reemplazar el contenido completo de `requirements.txt` por:

```
requests>=2.33.0
openpyxl>=3.1.0
python-dotenv>=1.0.0
apify-client>=1.6.0
schedule>=1.2.0
python-dateutil>=2.9.0
pytest>=8.0.0
```

Luego: `pip install -r requirements.txt`

- [ ] **Step 5: Añadir las constantes nuevas a `config.py`**

Borrar las líneas de Supabase (`SUPABASE_URL`, `SUPABASE_KEY`) y añadir al final del archivo:

```python
# ── v2 ────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/avianca.db")

BACKFILL_SINCE = "2026-04-19"

# Drivers operativos de queja — el LLM debe devolver exactamente uno de estos
COMPLAINT_DRIVERS = [
    "equipaje",
    "cancelacion",
    "demora",
    "atencion_cliente",
    "cobros_tarifas",
    "lifemiles",
    "asientos_comida",
    "reembolsos",
    "otro",
]

# Raíces de dominio de agregadores/OTAs que generan ruido SEO.
# El match es por etiqueta de dominio, así que "rehlat" atrapa
# rehlat.es, au.rehlat.com, www.rehlat.mx, jo.rehlat.com, etc.
BLACKLIST_DOMAIN_ROOTS = {
    "rehlat", "jetcost", "kayak", "despegar", "kiwi", "skyscanner",
    "expedia", "trip", "edreams", "viajala", "momondo", "cheapflights",
    "tidal", "atoallinks",
}

SPANISH_STOPWORDS = {
    "que", "para", "con", "los", "las", "del", "una", "por", "como",
    "pero", "más", "mas", "este", "esta", "sus", "muy",
}

# Nº mínimo de palabras para que valga la pena juzgar el idioma
LANG_MIN_WORDS = 15
# Nº de stopwords españolas distintas requeridas por encima de ese umbral
LANG_MIN_STOPWORDS = 2

# Instagram: cuántos posts del perfil recorrer para cubrir 4 meses
INSTAGRAM_POSTS_LIMIT = 80
```

- [ ] **Step 6: Crear `store/__init__.py` (vacío) y `data/.gitkeep` (vacío)**

- [ ] **Step 7: Crear `tests/__init__.py` (vacío) y `tests/conftest.py`**

```python
import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Conexión SQLite en disco temporal, con el schema v2 aplicado."""
    from store import db
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()
```

- [ ] **Step 8: Verificar que pytest arranca**

Run: `python -m pytest --collect-only`
Expected: `no tests ran` sin errores de import. (`tmp_db` fallará al usarse hasta la Task 3; aquí solo verificamos que pytest carga.)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: andamiaje de tests y constantes de config para v2"
```

---

## Task 2: Filtro de relevancia

**Files:**
- Create: `pipeline/relevance.py`, `tests/test_relevance.py`

**Interfaces:**
- Consumes: `config.BLACKLIST_DOMAIN_ROOTS`, `config.SPANISH_STOPWORDS`, `config.LANG_MIN_WORDS`, `config.LANG_MIN_STOPWORDS`, `config.BRAND_DOMAINS`, `config.BRAND_KEYWORD`
- Produces:
  - `is_spanish(text: str) -> bool`
  - `is_relevant(mention: dict) -> tuple[bool, str]` — devuelve `(True, "")` si pasa, o `(False, razon)` donde razón ∈ `{"dominio_oficial", "agregador", "idioma", "sin_keyword"}`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_relevance.py`:

```python
from pipeline.relevance import is_relevant, is_spanish


def _web(text, author):
    return {"platform": "web", "text": text, "author": author}


TEXTO_ES = (
    "Volé con Avianca desde Bogotá y la verdad el servicio fue muy malo, "
    "perdieron mi maleta y nadie me dio una respuesta clara en el aeropuerto"
)


def test_pasa_mencion_web_legitima():
    ok, razon = is_relevant(_web(TEXTO_ES, "blogdeviajes.co"))
    assert ok is True
    assert razon == ""


def test_descarta_dominio_oficial():
    ok, razon = is_relevant(_web(TEXTO_ES, "www.avianca.com"))
    assert ok is False
    assert razon == "dominio_oficial"


def test_descarta_agregador_en_cualquier_tld():
    for dominio in ["rehlat.es", "au.rehlat.com", "www.rehlat.mx", "jo.rehlat.com"]:
        ok, razon = is_relevant(_web(TEXTO_ES, dominio))
        assert ok is False, dominio
        assert razon == "agregador", dominio


def test_descarta_tidal_y_jetcost():
    assert is_relevant(_web(TEXTO_ES, "tidal.com"))[1] == "agregador"
    assert is_relevant(_web(TEXTO_ES, "www.jetcost.pl"))[1] == "agregador"


def test_descarta_texto_en_otro_idioma():
    polaco = (
        "Daty podrozy w znaczacy sposob wplywaja na cene biletow lotniczych "
        "Jetcost pozwala wyszukac bilety lotnicze linii Avianca oraz innych "
        "przewoznikow dostepnych w naszej wyszukiwarce lotow online"
    )
    ok, razon = is_relevant(_web(polaco, "ejemplo.com"))
    assert ok is False
    assert razon == "idioma"


def test_descarta_texto_sin_la_palabra_avianca():
    texto = (
        "Los precios de los tiquetes aéreos para las vacaciones de fin de año "
        "subieron mucho este año según los datos que publicó el gremio del sector"
    )
    ok, razon = is_relevant(_web(texto, "ejemplo.com"))
    assert ok is False
    assert razon == "sin_keyword"


def test_texto_corto_no_se_filtra_por_idioma():
    # Menos de 15 palabras: demasiado corto para juzgar idioma
    assert is_spanish("Avianca perdió mi maleta otra vez") is True


def test_contenido_social_pasa_sin_evaluar():
    ok, razon = is_relevant({"platform": "instagram", "text": "ok", "author": "user1"})
    assert ok is True
    assert razon == ""
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_relevance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.relevance'`

- [ ] **Step 3: Implementar `pipeline/relevance.py`**

```python
"""
Filtro de relevancia para menciones web.

Responde una sola pregunta: ¿esta mención habla de Avianca-la-aerolínea,
o es ruido SEO de un agregador de vuelos?

Función pura: sin red, sin DB, sin estado. El contenido social (instagram,
tiktok) pasa directo porque ya viene de perfiles y hashtags de la marca.
"""
import re

from config import (
    BLACKLIST_DOMAIN_ROOTS,
    BRAND_DOMAINS,
    BRAND_KEYWORD,
    LANG_MIN_STOPWORDS,
    LANG_MIN_WORDS,
    SPANISH_STOPWORDS,
)

_BRAND_DOMAINS = BRAND_DOMAINS.get(BRAND_KEYWORD, set())
_WORD_RE = re.compile(r"[a-záéíóúñü]+")


def is_spanish(text: str) -> bool:
    """
    Heurística sin dependencias: cuenta stopwords españolas distintas.

    Los textos de menos de LANG_MIN_WORDS palabras se dan por válidos —
    son demasiado cortos para decidir, y el filtro de keyword los cubre.
    """
    words = _WORD_RE.findall(text.lower())
    if len(words) < LANG_MIN_WORDS:
        return True
    hits = {w for w in words if w in SPANISH_STOPWORDS}
    return len(hits) >= LANG_MIN_STOPWORDS


def _is_blacklisted(domain: str) -> bool:
    """
    Match por etiqueta de dominio, no por string completo.
    Así una sola entrada "rehlat" atrapa rehlat.es, au.rehlat.com y www.rehlat.mx.
    """
    return any(label in BLACKLIST_DOMAIN_ROOTS for label in domain.split("."))


def is_relevant(mention: dict) -> tuple[bool, str]:
    """
    Devuelve (pasa, razon_de_descarte).
    razon es "" cuando pasa.
    """
    if mention.get("platform") != "web":
        return True, ""

    domain = (mention.get("author") or "").lower().strip()

    if domain in _BRAND_DOMAINS:
        return False, "dominio_oficial"

    if _is_blacklisted(domain):
        return False, "agregador"

    text = mention.get("text") or ""

    if not is_spanish(text):
        return False, "idioma"

    if BRAND_KEYWORD.lower() not in text.lower():
        return False, "sin_keyword"

    return True, ""
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_relevance.py -v`
Expected: PASS — 8 tests

- [ ] **Step 5: Validar contra el dataset real**

Este paso confirma el efecto esperado del spec (§5) sobre las 100 filas web reales.

```bash
PYTHONIOENCODING=utf-8 python -c "
import openpyxl, collections
from pipeline.relevance import is_relevant
ws = openpyxl.load_workbook('avianca_mentions_2026-06-05.xlsx').active
rows = list(ws.iter_rows(values_only=True)); hdr = list(rows[0])
i = {h: n for n, h in enumerate(hdr)}
web = [r for r in rows[1:] if r[i['Plataforma']] == 'web']
razones = collections.Counter()
pasan = 0
for r in web:
    ok, razon = is_relevant({'platform':'web','text':r[i['Texto']] or '','author':r[i['Autor']] or ''})
    if ok: pasan += 1
    else: razones[razon] += 1
print('web totales:', len(web), '| pasan:', pasan)
print('descartadas por:', dict(razones))
"
```

Expected: las ~63 filas de `rehlat` aparecen bajo `agregador`, y el total que pasa es una fracción pequeña de 100. Si `pasan` es 0, revisar que el umbral de idioma no sea demasiado agresivo antes de continuar.

- [ ] **Step 6: Commit**

```bash
git add pipeline/relevance.py tests/test_relevance.py
git commit -m "feat: filtro de relevancia para menciones web"
```

---

## Task 3: Store SQLite

**Files:**
- Create: `store/db.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: `config.DB_PATH`
- Produces:
  - `init_db(conn: sqlite3.Connection) -> None`
  - `connect(path: str = DB_PATH) -> sqlite3.Connection`
  - `fingerprint(platform: str, source_url: str, text: str) -> str`
  - `start_run(conn, mode: str, since: str | None) -> str` — devuelve `run_id`
  - `finish_run(conn, run_id: str, raw_count: int, filtered_count: int, inserted_count: int, duplicate_count: int, notes: str) -> None`
  - `upsert_mentions(conn, mentions: list[dict], run_id: str) -> tuple[int, int]` — devuelve `(insertadas, duplicadas)`
  - `pending_classification(conn) -> list[dict]`
  - `update_classification(conn, mention_id: str, result: dict) -> None`
  - `all_mentions(conn) -> list[dict]`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_db.py`:

```python
from store import db


def _mention(text="Avianca me perdió la maleta en Bogotá",
             url="https://x.com/1", mid="m-1"):
    return {
        "id": mid,
        "platform": "tiktok",
        "source_url": url,
        "text": text,
        "author": "usuario1",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10,
        "shares": 2,
        "comments_count": 3,
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.0,
        "sentiment_neutral": 1.0,
        "emotion": "neutral",
        "is_complaint": 0,
        "complaint_driver": None,
        "classification_status": "unclassified",
        "raw": {"foo": "bar"},
        "fetched_at": "2026-08-19T00:00:00+00:00",
    }


def test_fingerprint_es_estable_y_ignora_id():
    a = db.fingerprint("tiktok", "https://x.com/1", "hola mundo")
    b = db.fingerprint("tiktok", "https://x.com/1", "hola mundo")
    assert a == b
    assert len(a) == 64


def test_fingerprint_distingue_texto_distinto_en_misma_url():
    a = db.fingerprint("tiktok", "https://x.com/1", "hola mundo")
    b = db.fingerprint("tiktok", "https://x.com/1", "otro comentario distinto")
    assert a != b


def test_insertar_menciones_nuevas(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert (ins, dup) == (1, 0)
    assert len(db.all_mentions(tmp_db)) == 1


def test_reinsertar_el_mismo_lote_es_idempotente(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    run_2 = db.start_run(tmp_db, "weekly", None)
    ins, dup = db.upsert_mentions(tmp_db, [_mention()], run_2)
    assert (ins, dup) == (0, 1)
    assert len(db.all_mentions(tmp_db)) == 1


def test_run_id_conserva_la_primera_corrida(tmp_db):
    run_1 = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_1)
    run_2 = db.start_run(tmp_db, "weekly", None)
    db.upsert_mentions(tmp_db, [_mention()], run_2)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["run_id"] == run_1


def test_mismo_url_distinto_texto_si_inserta(tmp_db):
    """Dos comentarios distintos pueden vivir en la misma URL — por eso el
    dedup va por fingerprint del contenido y no por source_url."""
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(mid="m-1"),
            _mention(mid="m-2", text="Otro comentario totalmente diferente aquí"),
        ],
        run_id,
    )
    assert (ins, dup) == (2, 0)
    assert len(db.all_mentions(tmp_db)) == 2


def test_pending_classification_devuelve_solo_unclassified(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    pendientes = db.pending_classification(tmp_db)
    assert len(pendientes) == 1

    db.update_classification(tmp_db, pendientes[0]["id"], {
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.9,
        "sentiment_neutral": 0.1,
        "emotion": "anger",
        "is_complaint": True,
        "complaint_driver": "equipaje",
    })

    assert db.pending_classification(tmp_db) == []
    fila = db.all_mentions(tmp_db)[0]
    assert fila["complaint_driver"] == "equipaje"
    assert fila["classification_status"] == "classified"
    assert fila["is_complaint"] == 1


def test_raw_se_guarda_y_recupera_como_dict(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert db.all_mentions(tmp_db)[0]["raw"] == {"foo": "bar"}


def test_finish_run_guarda_contadores(tmp_db):
    run_id = db.start_run(tmp_db, "backfill", "2026-04-19")
    db.finish_run(tmp_db, run_id, raw_count=10, filtered_count=3,
                  inserted_count=6, duplicate_count=1, notes="ok")
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["raw_count"] == 10
    assert fila["filtered_count"] == 3
    assert fila["since"] == "2026-04-19"
    assert fila["finished_at"] is not None
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'store.db'`

- [ ] **Step 3: Implementar `store/db.py`**

```python
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

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS mentions (
    id                    TEXT PRIMARY KEY,
    fingerprint           TEXT NOT NULL UNIQUE,
    platform              TEXT NOT NULL,
    source_url            TEXT,
    text                  TEXT NOT NULL,
    author                TEXT,
    published_at          TEXT,
    date_confidence       TEXT NOT NULL,
    country               TEXT,
    likes                 INTEGER DEFAULT 0,
    shares                INTEGER DEFAULT 0,
    comments_count        INTEGER DEFAULT 0,
    sentiment_positive    REAL,
    sentiment_negative    REAL,
    sentiment_neutral     REAL,
    emotion               TEXT,
    is_complaint          INTEGER DEFAULT 0,
    complaint_driver      TEXT,
    classification_status TEXT NOT NULL,
    raw                   TEXT,
    fetched_at            TEXT,
    run_id                TEXT
);

CREATE INDEX IF NOT EXISTS idx_mentions_published ON mentions(published_at);
CREATE INDEX IF NOT EXISTS idx_mentions_platform  ON mentions(platform);
CREATE INDEX IF NOT EXISTS idx_mentions_complaint ON mentions(is_complaint);
CREATE INDEX IF NOT EXISTS idx_mentions_driver    ON mentions(complaint_driver);
CREATE INDEX IF NOT EXISTS idx_mentions_status    ON mentions(classification_status);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    mode            TEXT NOT NULL,
    since           TEXT,
    raw_count       INTEGER DEFAULT 0,
    filtered_count  INTEGER DEFAULT 0,
    inserted_count  INTEGER DEFAULT 0,
    duplicate_count INTEGER DEFAULT 0,
    notes           TEXT
);
"""

_FIELDS = [
    "id", "fingerprint", "platform", "source_url", "text", "author",
    "published_at", "date_confidence", "country", "likes", "shares",
    "comments_count", "sentiment_positive", "sentiment_negative",
    "sentiment_neutral", "emotion", "is_complaint", "complaint_driver",
    "classification_status", "raw", "fetched_at", "run_id",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def fingerprint(platform: str, source_url: str, text: str) -> str:
    """
    Hash del contenido ya normalizado. Se calcula SIEMPRE después de
    normalizar — sobre texto crudo, un espacio distinto crearía un duplicado.
    """
    base = f"{platform}|{source_url or ''}|{(text or '')[:80]}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def start_run(conn: sqlite3.Connection, mode: str, since: str | None) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (id, started_at, mode, since) VALUES (?, ?, ?, ?)",
        (run_id, _now(), mode, since),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id, raw_count, filtered_count,
               inserted_count, duplicate_count, notes="") -> None:
    conn.execute(
        """UPDATE runs SET finished_at = ?, raw_count = ?, filtered_count = ?,
                           inserted_count = ?, duplicate_count = ?, notes = ?
           WHERE id = ?""",
        (_now(), raw_count, filtered_count, inserted_count,
         duplicate_count, notes, run_id),
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
        fp = fingerprint(m["platform"], m.get("source_url", ""), m["text"])
        row = {
            **{f: m.get(f) for f in _FIELDS},
            "id": m.get("id") or str(uuid.uuid4()),
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


def pending_classification(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM mentions WHERE classification_status = 'unclassified'"
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


def all_mentions(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM mentions ORDER BY published_at DESC").fetchall()
    return [_to_dict(r) for r in rows]
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS — 9 tests

- [ ] **Step 5: Commit**

```bash
git add store/db.py tests/test_db.py
git commit -m "feat: store SQLite con dedup por fingerprint y tracking de corridas"
```

---

## Task 4: Importar el Excel v1

**Files:**
- Create: `store/seed_excel.py`, `tests/test_seed_excel.py`

**Interfaces:**
- Consumes: `store.db.upsert_mentions`, `store.db.start_run`, `store.db.finish_run`, `pipeline.relevance.is_relevant`
- Produces:
  - `read_excel(path: str) -> list[dict]` — filas del Excel v1 mapeadas al schema v2
  - `seed(path: str, conn) -> dict` — devuelve `{"raw": int, "filtered": int, "inserted": int, "duplicates": int, "filter_reasons": dict[str, int]}`

**Contexto:** el Excel v1 tiene estas columnas exactas, con acentos y signo de apertura:
`¿Queja real?`, `Plataforma`, `Texto`, `Autor`, `Fecha publicación`, `URL`, `Likes`, `Shares`, `Comentarios`, `Sentiment +`, `Sentiment -`, `Sentiment =`, `Emoción`, `Extraído en`.

Todas las filas importadas entran como `unclassified` — ver spec §7. Las `web` nunca fueron analizadas, y las sociales no tienen `complaint_driver` porque el campo no existía en v1.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_seed_excel.py`:

```python
import openpyxl
import pytest

from store import db, seed_excel

HEADERS = [
    "¿Queja real?", "Plataforma", "Texto", "Autor", "Fecha publicación",
    "URL", "Likes", "Shares", "Comentarios", "Sentiment +", "Sentiment -",
    "Sentiment =", "Emoción", "Extraído en",
]

TEXTO_ES = (
    "Volé con Avianca desde Bogotá y perdieron mi maleta, "
    "nadie me dio una respuesta clara en el aeropuerto para nada"
)


@pytest.fixture
def excel_v1(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    # web con fecha falsa (published_at == fetched_at)
    ws.append(["no", "web", TEXTO_ES, "blogdeviajes.co",
               "2026-06-05T20:31:34+00:00", "https://blog.co/1",
               0, 0, 0, 0, 0, 1, "neutral", "2026-06-05T20:31:34+00:00"])
    # web ruido de agregador
    ws.append(["no", "web", TEXTO_ES, "www.rehlat.es",
               "2026-06-05T20:31:34+00:00", "https://rehlat.es/1",
               0, 0, 0, 0, 0, 1, "neutral", "2026-06-05T20:31:34+00:00"])
    # tiktok con fecha real
    ws.append(["SÍ ⚠️", "tiktok", "Avianca me canceló el vuelo sin avisar", "user1",
               "2026-03-02T12:00:00+00:00", "https://tiktok.com/1",
               100, 5, 3, 0.1, 0.8, 0.1, "anger", "2026-06-05T20:31:34+00:00"])
    path = tmp_path / "v1.xlsx"
    wb.save(path)
    return str(path)


def test_read_excel_mapea_al_schema_v2(excel_v1):
    filas = seed_excel.read_excel(excel_v1)
    assert len(filas) == 3
    assert {f["platform"] for f in filas} == {"web", "tiktok"}
    assert all(f["classification_status"] == "unclassified" for f in filas)


def test_web_con_fecha_igual_a_fetched_at_queda_unknown(excel_v1):
    filas = seed_excel.read_excel(excel_v1)
    web = [f for f in filas if f["platform"] == "web"]
    assert all(f["date_confidence"] == "unknown" for f in web)
    assert all(f["published_at"] is None for f in web)


def test_tiktok_conserva_fecha_como_exact(excel_v1):
    filas = seed_excel.read_excel(excel_v1)
    tk = [f for f in filas if f["platform"] == "tiktok"][0]
    assert tk["date_confidence"] == "exact"
    assert tk["published_at"].startswith("2026-03-02")


def test_seed_descarta_ruido_y_cuenta_razones(excel_v1, tmp_db):
    res = seed_excel.seed(excel_v1, tmp_db)
    assert res["raw"] == 3
    assert res["filtered"] == 1
    assert res["filter_reasons"]["agregador"] == 1
    assert res["inserted"] == 2


def test_seed_dos_veces_no_duplica(excel_v1, tmp_db):
    seed_excel.seed(excel_v1, tmp_db)
    res = seed_excel.seed(excel_v1, tmp_db)
    assert res["inserted"] == 0
    assert res["duplicates"] == 2
    assert len(db.all_mentions(tmp_db)) == 2
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_seed_excel.py -v`
Expected: FAIL — `ImportError: cannot import name 'seed_excel' from 'store'`

- [ ] **Step 3: Implementar `store/seed_excel.py`**

```python
"""
Importa el Excel del pipeline v1 al schema v2.

Rescata el histórico ya pagado (sobre todo TikTok, que tiene 4 meses reales)
sin volver a gastar en scraping.

Todas las filas entran como 'unclassified' a propósito:
  - Las web nunca fueron analizadas (DataForSEO devolvió sentiment vacío).
  - Las sociales no tienen complaint_driver porque el campo no existía en v1.
Reclasificar todo es lo único que deja el dataset homogéneo.
"""
import collections
import uuid

import openpyxl

from pipeline.relevance import is_relevant
from store import db

COLUMN_MAP = {
    "Plataforma": "platform",
    "Texto": "text",
    "Autor": "author",
    "Fecha publicación": "published_at",
    "URL": "source_url",
    "Likes": "likes",
    "Shares": "shares",
    "Comentarios": "comments_count",
    "Emoción": "emotion",
    "Extraído en": "fetched_at",
}


def _num(value, cast=int):
    try:
        return cast(value or 0)
    except (TypeError, ValueError):
        return cast(0)


def read_excel(path: str) -> list[dict]:
    ws = openpyxl.load_workbook(path).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = list(rows[0])
    index = {h: n for n, h in enumerate(headers)}
    out = []

    for row in rows[1:]:
        get = lambda col: row[index[col]] if col in index else None

        text = (get("Texto") or "").strip()
        if not text:
            continue

        published = get("Fecha publicación")
        fetched = get("Extraído en")
        published = str(published) if published else None
        fetched = str(fetched) if fetched else None

        # La fecha web del v1 es un fallback a fetched_at: no es una fecha real.
        if published and fetched and published == fetched:
            published, confidence = None, "unknown"
        elif published:
            confidence = "exact"
        else:
            confidence = "unknown"

        out.append({
            "id": str(uuid.uuid4()),
            "platform": get("Plataforma"),
            "source_url": get("URL") or "",
            "text": text,
            "author": get("Autor"),
            "published_at": published,
            "date_confidence": confidence,
            "country": "CO",
            "likes": _num(get("Likes")),
            "shares": _num(get("Shares")),
            "comments_count": _num(get("Comentarios")),
            "sentiment_positive": None,
            "sentiment_negative": None,
            "sentiment_neutral": None,
            "emotion": None,
            "is_complaint": 0,
            "complaint_driver": None,
            "classification_status": "unclassified",
            "raw": {"origen": "seed_excel_v1"},
            "fetched_at": fetched,
        })

    return out


def seed(path: str, conn) -> dict:
    filas = read_excel(path)
    run_id = db.start_run(conn, "seed", None)

    razones = collections.Counter()
    keep = []
    for m in filas:
        ok, razon = is_relevant(m)
        if ok:
            keep.append(m)
        else:
            razones[razon] += 1

    inserted, duplicates = db.upsert_mentions(conn, keep, run_id)

    db.finish_run(
        conn, run_id,
        raw_count=len(filas),
        filtered_count=len(filas) - len(keep),
        inserted_count=inserted,
        duplicate_count=duplicates,
        notes=f"seed desde {path}",
    )

    return {
        "raw": len(filas),
        "filtered": len(filas) - len(keep),
        "inserted": inserted,
        "duplicates": duplicates,
        "filter_reasons": dict(razones),
    }
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_seed_excel.py -v`
Expected: PASS — 5 tests

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -v`
Expected: PASS — 22 tests (8 relevance + 9 db + 5 seed)

- [ ] **Step 6: Commit**

```bash
git add store/seed_excel.py tests/test_seed_excel.py
git commit -m "feat: importador del Excel v1 al store v2"
```

---

## Task 5: Honestidad de fechas — normalizer y scrapers

**Files:**
- Modify: `pipeline/normalizer.py`, `scrapers/dataforseo_scraper.py`, `scrapers/apify_tiktok.py`, `scrapers/apify_instagram.py`
- Create: `tests/test_normalizer.py`

**Interfaces:**
- Consumes: nada nuevo
- Produces: `normalize(mentions: list[dict]) -> list[dict]` — cada mención sale con `date_confidence` asignado y `published_at` que puede ser `None`

**Contexto:** hoy los tres scrapers hacen `item.get("fecha", fetched_at)`, lo que convierte "no sé cuándo se publicó" en "se publicó hoy". Esa es la razón de que las 100 menciones web digan todas 2026-06-05. Aquí se corta de raíz.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_normalizer.py`:

```python
from pipeline.normalizer import normalize

TEXTO = "Avianca me perdió la maleta en el aeropuerto de Bogotá otra vez"


def _m(**kw):
    base = {
        "platform": "tiktok",
        "text": TEXTO,
        "source_url": "https://x.com/1",
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.0,
        "sentiment_neutral": 1.0,
    }
    base.update(kw)
    return base


def test_fecha_presente_queda_exact():
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00")])
    assert out[0]["date_confidence"] == "exact"
    assert out[0]["published_at"] == "2026-05-01T10:00:00+00:00"


def test_fecha_ausente_queda_unknown_y_no_se_inventa():
    out = normalize([_m(published_at=None)])
    assert out[0]["date_confidence"] == "unknown"
    assert out[0]["published_at"] is None


def test_fecha_ausente_como_string_vacio_tambien_es_unknown():
    out = normalize([_m(published_at="")])
    assert out[0]["date_confidence"] == "unknown"
    assert out[0]["published_at"] is None


def test_confidence_explicito_del_scraper_se_respeta():
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00",
                        date_confidence="approx")])
    assert out[0]["date_confidence"] == "approx"


def test_descarta_textos_muy_cortos():
    assert normalize([_m(text="hola")]) == []


def test_normaliza_sentiment_que_no_suma_uno():
    out = normalize([_m(published_at="2026-05-01T10:00:00+00:00",
                        sentiment_positive=1.0,
                        sentiment_negative=1.0,
                        sentiment_neutral=2.0)])
    total = (out[0]["sentiment_positive"] + out[0]["sentiment_negative"]
             + out[0]["sentiment_neutral"])
    assert abs(total - 1.0) < 0.01
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_normalizer.py -v`
Expected: FAIL — `test_fecha_ausente_queda_unknown_y_no_se_inventa` falla porque el normalizer actual rellena con `datetime.now()`; los tests de `date_confidence` fallan con `KeyError`.

- [ ] **Step 3: Reescribir `pipeline/normalizer.py`**

```python
"""
Normalizer: valida y limpia el schema unificado.

Regla dura: si no hay fecha de publicación, published_at queda None y
date_confidence queda 'unknown'. NUNCA se sustituye por fetched_at —
eso fue lo que hizo que las 100 menciones web del v1 dijeran todas
la misma fecha.
"""

MIN_TEXT_LENGTH = 10


def normalize(mentions: list[dict]) -> list[dict]:
    clean = []

    for m in mentions:
        text = (m.get("text") or "").strip()
        if len(text) < MIN_TEXT_LENGTH:
            continue

        pos = float(m.get("sentiment_positive") or 0.0)
        neg = float(m.get("sentiment_negative") or 0.0)
        neu = float(m.get("sentiment_neutral") or 0.0)
        total = pos + neg + neu
        if total > 0 and abs(total - 1.0) > 0.05:
            pos, neg, neu = pos / total, neg / total, neu / total

        published = m.get("published_at") or None
        confidence = m.get("date_confidence")
        if not confidence:
            confidence = "exact" if published else "unknown"
        if not published:
            confidence = "unknown"

        clean.append({
            **m,
            "text": text,
            "published_at": published,
            "date_confidence": confidence,
            "sentiment_positive": round(pos, 4),
            "sentiment_negative": round(neg, 4),
            "sentiment_neutral": round(neu, 4),
            "likes": int(m.get("likes") or 0),
            "shares": int(m.get("shares") or 0),
            "comments_count": int(m.get("comments_count") or 0),
            "is_complaint": bool(m.get("is_complaint", False)),
        })

    print(f"[Normalizer] {len(clean)}/{len(mentions)} menciones válidas")
    return clean
```

- [ ] **Step 4: Quitar los fallbacks de fecha en los tres scrapers**

En `scrapers/dataforseo_scraper.py`, dentro del `results.append({...})`:

```python
            "published_at": item.get("date_published") or None,
```

(antes decía `item.get("date_published", fetched_at)`)

En `scrapers/apify_tiktok.py`:

```python
            "published_at": item.get("createTimeISO") or None,
```

En `scrapers/apify_instagram.py`:

```python
            "published_at": timestamp or None,
```

- [ ] **Step 5: Quitar la heurística de queja de DataForSEO**

En `scrapers/dataforseo_scraper.py`, borrar estas dos líneas:

```python
        # Queja real = sentiment negativo dominante en fuente independiente
        is_complaint = neg > 0.4 and neg > pos
```

y en el dict de resultado dejar:

```python
            "is_complaint": False,
```

El clasificador (Task 6) es ahora la única autoridad sobre qué es una queja, en todas las plataformas.

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_normalizer.py -v`
Expected: PASS — 6 tests

Run: `python -m pytest -v`
Expected: PASS — 28 tests

- [ ] **Step 7: Commit**

```bash
git add pipeline/normalizer.py scrapers/ tests/test_normalizer.py
git commit -m "fix: dejar de inventar fechas de publicación; date_confidence explícito"
```

---

## Task 6: Clasificador con drivers de queja

**Files:**
- Create: `pipeline/classifier.py`, `tests/test_classifier.py`
- Delete: `pipeline/sentiment_engine.py`

**Interfaces:**
- Consumes: `config.DEEPSEEK_API_KEY`, `config.COMPLAINT_DRIVERS`
- Produces:
  - `normalize_result(raw: dict) -> dict` — sanea una respuesta del LLM al contrato
  - `classify_texts(texts: list[str]) -> list[dict | None]` — un `None` por texto que no se pudo clasificar
  - `SYSTEM_PROMPT: str`
  - `NEUTRAL: dict` (constante de fallback)

**Contrato de salida por mención:**

```json
{"sentiment_positive": 0.0, "sentiment_negative": 0.0, "sentiment_neutral": 1.0,
 "emotion": "happiness", "is_complaint": false, "complaint_driver": null}
```

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_classifier.py`:

```python
import json
from unittest.mock import MagicMock, patch

from pipeline import classifier


def _api_response(payload):
    """Simula la envoltura de respuesta de DeepSeek."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]
    }
    return resp


OK = {
    "sentiment_positive": 0.0, "sentiment_negative": 0.9,
    "sentiment_neutral": 0.1, "emotion": "anger",
    "is_complaint": True, "complaint_driver": "equipaje",
}


def test_normaliza_respuesta_valida():
    out = classifier.normalize_result(OK)
    assert out["complaint_driver"] == "equipaje"
    assert out["is_complaint"] is True
    assert out["emotion"] == "anger"


def test_driver_invalido_se_mapea_a_otro():
    out = classifier.normalize_result({**OK, "complaint_driver": "wifi_del_avion"})
    assert out["complaint_driver"] == "otro"


def test_queja_sin_driver_recibe_otro():
    out = classifier.normalize_result({**OK, "complaint_driver": None})
    assert out["complaint_driver"] == "otro"


def test_no_queja_fuerza_driver_nulo():
    out = classifier.normalize_result({**OK, "is_complaint": False})
    assert out["complaint_driver"] is None


def test_emocion_invalida_se_mapea_a_neutral():
    out = classifier.normalize_result({**OK, "emotion": "euforia"})
    assert out["emotion"] == "neutral"


def test_sentiment_se_renormaliza_a_uno():
    out = classifier.normalize_result({
        **OK, "sentiment_positive": 2.0,
        "sentiment_negative": 2.0, "sentiment_neutral": 0.0,
    })
    total = (out["sentiment_positive"] + out["sentiment_negative"]
             + out["sentiment_neutral"])
    assert abs(total - 1.0) < 0.01


@patch("pipeline.classifier.requests.post")
def test_batch_feliz(mock_post):
    mock_post.return_value = _api_response([OK, OK])
    out = classifier.classify_texts(["texto uno", "texto dos"])
    assert len(out) == 2
    assert all(o["complaint_driver"] == "equipaje" for o in out)
    assert mock_post.call_count == 1


@patch("pipeline.classifier.requests.post")
def test_longitud_desigual_no_hace_zip_y_cae_a_item_por_item(mock_post):
    # 1º llamado (batch de 2) devuelve 1 objeto → inválido
    # 2º llamado (reintento del batch) devuelve 1 objeto → inválido otra vez
    # 3º y 4º llamados (item por item) devuelven 1 objeto cada uno → válidos
    mock_post.side_effect = [
        _api_response([OK]),
        _api_response([OK]),
        _api_response([OK]),
        _api_response([OK]),
    ]
    out = classifier.classify_texts(["texto uno", "texto dos"])
    assert len(out) == 2
    assert all(o is not None for o in out)
    assert mock_post.call_count == 4


@patch("pipeline.classifier.requests.post")
def test_parsea_respuesta_envuelta_en_fences(mock_post):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {
        "content": "```json\n" + json.dumps([OK]) + "\n```"
    }}]}
    mock_post.return_value = resp
    out = classifier.classify_texts(["texto uno"])
    assert out[0]["complaint_driver"] == "equipaje"


@patch("pipeline.classifier.requests.post")
def test_fallo_total_devuelve_none_no_neutral(mock_post):
    mock_post.side_effect = Exception("boom")
    out = classifier.classify_texts(["texto uno"])
    assert out == [None]
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.classifier'`

- [ ] **Step 3: Implementar `pipeline/classifier.py`**

```python
"""
Clasificador de menciones. Único módulo que habla con DeepSeek.

Un solo llamado devuelve sentiment, emoción, si es queja y el driver
operativo — el driver sale gratis, va en el mismo prompt.

Diferencias clave con el sentiment_engine del v1:
  - TODAS las plataformas pasan por aquí, incluida 'web'. DataForSEO
    devolvió connotation_types vacío, así que sus menciones nunca se
    analizaron.
  - Si la respuesta no tiene la misma longitud que el batch, NO se hace
    zip (eso truncaba en silencio). Se reintenta y luego se cae a
    item por item.
  - Lo que no se logra clasificar devuelve None, no un neutral falso.
"""
import json
import time

import requests

from config import COMPLAINT_DRIVERS, DEEPSEEK_API_KEY

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

BATCH_SIZE = 10
MAX_RETRIES = 2

VALID_EMOTIONS = {"happiness", "anger", "love", "sadness", "neutral"}

NEUTRAL = {
    "sentiment_positive": 0.0,
    "sentiment_negative": 0.0,
    "sentiment_neutral": 1.0,
    "emotion": "neutral",
    "is_complaint": False,
    "complaint_driver": None,
}

SYSTEM_PROMPT = f"""Eres un analizador de menciones de marca en español latinoamericano, especializado en la aerolínea Avianca en Colombia.

Para cada texto retorna ÚNICAMENTE un JSON con este formato exacto:
{{
  "sentiment_positive": 0.0,
  "sentiment_negative": 0.0,
  "sentiment_neutral": 1.0,
  "emotion": "happiness",
  "is_complaint": false,
  "complaint_driver": null
}}

Reglas:
- Los tres valores de sentiment deben sumar 1.0
- emotion es exactamente uno de: "happiness", "anger", "love", "sadness", "neutral"
- is_complaint es true SOLO si es una queja real de un usuario sobre el servicio.
  Es false para contenido promocional, noticias, opinión neutral o contenido positivo.
- complaint_driver es null cuando is_complaint es false.
  Cuando is_complaint es true, es OBLIGATORIO y debe ser exactamente uno de:
    "equipaje"          — maletas perdidas, dañadas, demoradas, cobros de equipaje
    "cancelacion"       — vuelos cancelados, reprogramados sin aviso
    "demora"            — retrasos, conexiones perdidas por retraso
    "atencion_cliente"  — mal trato, call center, falta de respuesta, personal
    "cobros_tarifas"    — cobros indebidos, precios, cargos ocultos, penalidades
    "lifemiles"         — millas, programa de fidelidad, redenciones
    "asientos_comida"   — asientos, espacio, comida a bordo, entretenimiento
    "reembolsos"        — devoluciones de dinero que no llegan o se demoran
    "otro"              — queja real que no encaja en ninguna de las anteriores
- Ante duda sobre la categoría de una queja real, usa "otro".
- Sé preciso con el español coloquial colombiano."""


def _clamp(value, default=0.0):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def normalize_result(raw: dict) -> dict:
    """Sanea la respuesta del modelo al contrato. Nunca lanza."""
    if not isinstance(raw, dict):
        return dict(NEUTRAL)

    pos = _clamp(raw.get("sentiment_positive"))
    neg = _clamp(raw.get("sentiment_negative"))
    neu = _clamp(raw.get("sentiment_neutral"))
    total = pos + neg + neu
    if total <= 0:
        pos, neg, neu = 0.0, 0.0, 1.0
    elif abs(total - 1.0) > 0.05:
        pos, neg, neu = pos / total, neg / total, neu / total

    emotion = raw.get("emotion")
    if emotion not in VALID_EMOTIONS:
        emotion = "neutral"

    is_complaint = bool(raw.get("is_complaint", False))

    driver = raw.get("complaint_driver")
    if not is_complaint:
        driver = None
    elif driver not in COMPLAINT_DRIVERS:
        driver = "otro"

    return {
        "sentiment_positive": round(pos, 4),
        "sentiment_negative": round(neg, 4),
        "sentiment_neutral": round(neu, 4),
        "emotion": emotion,
        "is_complaint": is_complaint,
        "complaint_driver": driver,
    }


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _call_api(texts: list[str]) -> list[dict]:
    """
    Un llamado a DeepSeek. Lanza si la respuesta no es una lista del
    mismo largo que la entrada — nunca hace zip a ciegas.
    """
    prompt = (
        f"Analiza cada uno de los siguientes {len(texts)} textos sobre Avianca.\n"
        f"Retorna un array JSON con exactamente {len(texts)} objetos, en el mismo orden.\n"
        "No incluyas texto antes ni después del JSON.\n\n"
        f"Textos:\n{json.dumps(texts, ensure_ascii=False, indent=2)}\n\n"
        "Responde SOLO con el array JSON:"
    )

    response = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        },
        timeout=60,
    )
    response.raise_for_status()

    content = _strip_fences(response.json()["choices"][0]["message"]["content"])
    parsed = json.loads(content)

    if not isinstance(parsed, list):
        raise ValueError("la respuesta no es un array")
    if len(parsed) != len(texts):
        raise ValueError(
            f"longitud desigual: se pidieron {len(texts)}, llegaron {len(parsed)}"
        )

    return [normalize_result(p) for p in parsed]


def _attempt(texts: list[str]) -> list[dict] | None:
    """Intenta un batch con reintentos. Devuelve None si nunca funcionó."""
    for intento in range(MAX_RETRIES + 1):
        try:
            return _call_api(texts)
        except Exception as e:
            print(f"[Classifier] intento {intento + 1} falló: {e}")
            if intento < MAX_RETRIES:
                time.sleep(2 ** intento)
    return None


def classify_texts(texts: list[str]) -> list[dict | None]:
    """
    Clasifica una lista de textos. Devuelve una lista del mismo largo:
    un dict por texto clasificado, o None por texto que no se pudo clasificar.

    Estrategia: batch completo → reintentos → item por item.
    """
    if not texts:
        return []

    results: list[dict | None] = []

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]

        batch_result = _attempt(batch)
        if batch_result is not None:
            results.extend(batch_result)
            continue

        # El batch no salió ni con reintentos: uno por uno.
        print(f"[Classifier] batch de {len(batch)} falló; cayendo a item por item")
        for text in batch:
            single = _attempt([text])
            results.append(single[0] if single else None)

    return results
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_classifier.py -v`
Expected: PASS — 10 tests

- [ ] **Step 5: Borrar el motor viejo**

```bash
git rm pipeline/sentiment_engine.py
```

- [ ] **Step 6: Correr toda la suite**

Run: `python -m pytest -v`
Expected: PASS — 38 tests

- [ ] **Step 7: Commit**

```bash
git add pipeline/classifier.py tests/test_classifier.py
git commit -m "feat: clasificador con drivers de queja, reintentos y fallo explícito"
```

---

## Task 7: Clasificar lo pendiente en la DB

**Files:**
- Create: `pipeline/classify_pending.py`, `tests/test_classify_pending.py`

**Interfaces:**
- Consumes: `store.db.pending_classification`, `store.db.update_classification`, `pipeline.classifier.classify_texts`
- Produces: `run(conn) -> dict` — devuelve `{"pendientes": int, "clasificadas": int, "fallidas": int}`

**Por qué es una tarea aparte:** clasificar es una operación sobre el estado de la DB, no sobre un lote en memoria. Separarla permite reclasificar el seed sin re-scrapear, y permite reintentar lo que falló en una corrida anterior con solo volver a llamarla.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_classify_pending.py`:

```python
from unittest.mock import patch

from pipeline import classify_pending
from store import db

CLASIFICADO = {
    "sentiment_positive": 0.0, "sentiment_negative": 0.9,
    "sentiment_neutral": 0.1, "emotion": "anger",
    "is_complaint": True, "complaint_driver": "equipaje",
}


def _mention(idx):
    return {
        "id": f"m-{idx}",
        "platform": "tiktok",
        "source_url": f"https://x.com/{idx}",
        "text": f"Avianca me perdió la maleta numero {idx} en Bogotá",
        "author": "user",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 0, "shares": 0, "comments_count": 0,
        "classification_status": "unclassified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }


@patch("pipeline.classify_pending.classify_texts")
def test_clasifica_todo_lo_pendiente(mock_classify, tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(1), _mention(2)], run_id)
    mock_classify.return_value = [CLASIFICADO, CLASIFICADO]

    res = classify_pending.run(tmp_db)

    assert res == {"pendientes": 2, "clasificadas": 2, "fallidas": 0}
    assert db.pending_classification(tmp_db) == []
    assert all(m["complaint_driver"] == "equipaje" for m in db.all_mentions(tmp_db))


@patch("pipeline.classify_pending.classify_texts")
def test_los_none_quedan_unclassified(mock_classify, tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(1), _mention(2)], run_id)
    mock_classify.return_value = [CLASIFICADO, None]

    res = classify_pending.run(tmp_db)

    assert res == {"pendientes": 2, "clasificadas": 1, "fallidas": 1}
    assert len(db.pending_classification(tmp_db)) == 1


@patch("pipeline.classify_pending.classify_texts")
def test_sin_pendientes_no_llama_al_modelo(mock_classify, tmp_db):
    res = classify_pending.run(tmp_db)
    assert res == {"pendientes": 0, "clasificadas": 0, "fallidas": 0}
    mock_classify.assert_not_called()
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_classify_pending.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.classify_pending'`

- [ ] **Step 3: Implementar `pipeline/classify_pending.py`**

```python
"""
Clasifica todas las menciones que están 'unclassified' en la DB.

Es idempotente y reanudable: lo que falló en una corrida sigue pendiente,
así que basta volver a llamarla para reintentarlo, sin re-scrapear nada.
"""
from pipeline.classifier import classify_texts
from store import db


def run(conn) -> dict:
    pendientes = db.pending_classification(conn)
    if not pendientes:
        print("[Classify] nada pendiente")
        return {"pendientes": 0, "clasificadas": 0, "fallidas": 0}

    print(f"[Classify] clasificando {len(pendientes)} menciones...")
    resultados = classify_texts([m["text"] for m in pendientes])

    clasificadas = 0
    fallidas = 0

    for mention, resultado in zip(pendientes, resultados):
        if resultado is None:
            fallidas += 1
            continue
        db.update_classification(conn, mention["id"], resultado)
        clasificadas += 1

    print(f"[Classify] {clasificadas} clasificadas, {fallidas} fallidas")
    return {
        "pendientes": len(pendientes),
        "clasificadas": clasificadas,
        "fallidas": fallidas,
    }
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_classify_pending.py -v`
Expected: PASS — 3 tests

- [ ] **Step 5: Commit**

```bash
git add pipeline/classify_pending.py tests/test_classify_pending.py
git commit -m "feat: clasificación reanudable de menciones pendientes"
```

---

## Task 8: Scrapers con rango de fechas

**Files:**
- Modify: `scrapers/dataforseo_scraper.py`, `scrapers/apify_tiktok.py`, `scrapers/apify_instagram.py`

**Interfaces:**
- Consumes: `config.INSTAGRAM_POSTS_LIMIT`
- Produces: los tres scrapers exponen `scrape(since: str | None = None) -> list[dict]`, donde `since` es una fecha `YYYY-MM-DD`

**Nota:** estas funciones hablan con APIs de pago. No llevan tests unitarios; se verifican con una corrida acotada en el Step 5.

- [ ] **Step 1: `scrapers/dataforseo_scraper.py` acepta `since`**

Borrar la constante `DATE_FROM = "2026-01-01"` y cambiar la firma:

```python
def scrape(since: str | None = None) -> list[dict]:
    """
    Consulta DataForSEO y retorna menciones de usuarios.
    `since` es una fecha YYYY-MM-DD; si es None usa BACKFILL_SINCE.
    """
    payload = [{
        "keyword": BRAND_KEYWORD,
        "language_code": LANGUAGE_CODE,
        "limit": LIMIT_DATAFORSEO,
        "date_from": since or BACKFILL_SINCE,
    }]
```

Añadir `BACKFILL_SINCE` al import desde `config`.

- [ ] **Step 2: `scrapers/apify_tiktok.py` acepta `since`**

```python
def scrape(since: str | None = None) -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "hashtags": [BRAND_KEYWORD.lower(), f"{BRAND_KEYWORD.lower()}colombia"],
        "resultsPerPage": LIMIT_TIKTOK,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }
    if since:
        run_input["oldestPostDate"] = since
```

Y borrar el filtro por año hardcodeado (`if created_iso and not created_iso.startswith("2026")`), que ahora lo cubre `oldestPostDate`.

- [ ] **Step 3: `scrapers/apify_instagram.py` acepta `since` y sube el techo de posts**

```python
def scrape(since: str | None = None) -> list[dict]:
```

En la Fase 1, cambiar `"resultsLimit": 20` por `"resultsLimit": INSTAGRAM_POSTS_LIMIT` (importar de `config`).

En la Fase 2, cambiar `post_urls[:15]` por `post_urls` (ya viene acotado por `INSTAGRAM_POSTS_LIMIT`).

Reemplazar el filtro por año hardcodeado (`YEAR_FILTER`) por un filtro contra `since`:

```python
        timestamp = item.get("timestamp", "")
        if since and timestamp and str(timestamp)[:10] < since:
            continue
```

Borrar la constante `YEAR_FILTER = "2026"`.

- [ ] **Step 4: Verificar que la suite sigue verde**

Run: `python -m pytest -v`
Expected: PASS — 41 tests (los scrapers no tienen tests propios; se verifica que no se rompió nada)

- [ ] **Step 5: Prueba de humo acotada contra la API real**

Solo DataForSEO, que es la más barata y rápida:

```bash
PYTHONIOENCODING=utf-8 python -c "
from scrapers import dataforseo_scraper
r = dataforseo_scraper.scrape(since='2026-08-01')
print('menciones:', len(r))
if r:
    m = r[0]
    print('published_at:', m['published_at'])
    print('author:', m['author'])
    print('texto:', (m['text'] or '')[:100])
"
```

Expected: devuelve menciones sin lanzar excepción. Confirmar que `published_at` **no** es la fecha de hoy en todas las filas — si lo fuera, DataForSEO sigue sin devolver `date_published` y esas menciones caerán a `unknown`, que es el comportamiento correcto.

- [ ] **Step 6: Commit**

```bash
git add scrapers/
git commit -m "feat: rango de fechas configurable en los tres scrapers"
```

---

## Task 9: CLI y orquestación

**Files:**
- Modify: `main.py`
- Delete: `pipeline/supabase_writer.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: todo lo anterior
- Produces: `run_pipeline(mode: str, since: str | None) -> dict`

**Comandos finales:**

```
python main.py                                # corrida normal
python main.py --backfill                     # backfill desde config.BACKFILL_SINCE
python main.py --backfill --since 2026-04-19  # backfill desde una fecha
python main.py --seed-excel <archivo.xlsx>    # importa el Excel v1
python main.py --classify                     # solo reclasifica lo pendiente
python main.py --export-excel                 # vuelca la DB a .xlsx
python main.py --schedule                     # semanal, lunes 8am
```

**Sobre `--export-excel`:** el v1 generaba un `.xlsx` en cada corrida. En v2 la
fuente de verdad es SQLite, pero el export tabular sigue siendo útil para pasarle
la data cruda a alguien. Se conserva `pipeline/excel_writer.py` sin cambios y se
le da un flag propio en vez de correrlo en cada ejecución. Sus columnas
(`is_complaint`, `platform`, `text`, `emotion`, `fetched_at`, …) ya coinciden con
lo que devuelve `db.all_mentions()`.

- [ ] **Step 1: Reescribir `main.py`**

```python
"""
main.py — Entry point del pipeline Avianca Sentiment Monitor v2.

  python main.py                                # corrida normal
  python main.py --backfill                     # backfill desde config.BACKFILL_SINCE
  python main.py --backfill --since 2026-04-19  # backfill desde una fecha
  python main.py --seed-excel v1.xlsx           # importa el Excel del v1
  python main.py --classify                     # solo reclasifica lo pendiente
  python main.py --export-excel                 # vuelca la DB a .xlsx
  python main.py --schedule                     # semanal, lunes 8am

Twitter/X queda fuera de v2: el actor de Apify con búsqueda histórica
por rango de fechas es de pago. scrapers/apify_twitter.py se conserva
pero no está en SCRAPERS.
"""
import argparse
import collections
import sys
import time
from datetime import datetime, timezone

import schedule

from config import BACKFILL_SINCE
from pipeline import classify_pending
from pipeline.excel_writer import export as export_excel
from pipeline.normalizer import normalize
from pipeline.relevance import is_relevant
from scrapers import apify_instagram, apify_tiktok, dataforseo_scraper
from store import db, seed_excel

SCRAPERS = [
    ("DataForSEO", dataforseo_scraper.scrape),
    ("Instagram", apify_instagram.scrape),
    ("TikTok", apify_tiktok.scrape),
]


def run_pipeline(mode: str = "weekly", since: str | None = None) -> dict:
    print(f"\n{'=' * 56}")
    print(f"[Pipeline] {mode} | since={since or '—'} | {datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 56}\n")

    conn = db.connect()
    run_id = db.start_run(conn, mode, since)

    raw = []
    errores = []
    for nombre, scrape_fn in SCRAPERS:
        try:
            raw.extend(scrape_fn(since=since))
        except Exception as e:
            print(f"[{nombre}] ERROR: {e}")
            errores.append(f"{nombre}: {e}")

    print(f"\n[Pipeline] Total crudo: {len(raw)} menciones")

    normalizadas = normalize(raw)

    razones = collections.Counter()
    keep = []
    for m in normalizadas:
        ok, razon = is_relevant(m)
        if ok:
            keep.append(m)
        else:
            razones[razon] += 1

    if razones:
        print(f"[Relevance] descartadas: {dict(razones)}")

    inserted, duplicates = db.upsert_mentions(conn, keep, run_id)
    print(f"[Store] {inserted} nuevas, {duplicates} ya existían")

    clasificacion = classify_pending.run(conn)

    db.finish_run(
        conn, run_id,
        raw_count=len(raw),
        filtered_count=len(normalizadas) - len(keep),
        inserted_count=inserted,
        duplicate_count=duplicates,
        notes="; ".join(errores),
    )

    total = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
    conn.close()

    print(f"\n{'=' * 56}")
    print(f"[Pipeline] Completado. Total acumulado en DB: {total}")
    print(f"{'=' * 56}\n")

    return {
        "raw": len(raw),
        "inserted": inserted,
        "duplicates": duplicates,
        "total": total,
        **clasificacion,
    }


def main():
    parser = argparse.ArgumentParser(description="Avianca Sentiment Monitor v2")
    parser.add_argument("--backfill", action="store_true",
                        help="corrida histórica de 4 meses")
    parser.add_argument("--since", default=None,
                        help="fecha de inicio YYYY-MM-DD")
    parser.add_argument("--seed-excel", default=None,
                        help="importa un Excel del pipeline v1")
    parser.add_argument("--classify", action="store_true",
                        help="solo reclasifica lo pendiente en la DB")
    parser.add_argument("--export-excel", action="store_true",
                        help="vuelca la DB completa a un .xlsx")
    parser.add_argument("--schedule", action="store_true",
                        help="corre cada lunes a las 8am")
    args = parser.parse_args()

    if args.seed_excel:
        conn = db.connect()
        res = seed_excel.seed(args.seed_excel, conn)
        conn.close()
        print(f"[Seed] {res}")
        return

    if args.classify:
        conn = db.connect()
        print(f"[Classify] {classify_pending.run(conn)}")
        conn.close()
        return

    if args.export_excel:
        conn = db.connect()
        export_excel(db.all_mentions(conn))
        conn.close()
        return

    if args.schedule:
        print("[Scheduler] cada lunes a las 8am hora Colombia...")
        schedule.every().monday.at("08:00").do(run_pipeline)
        while True:
            schedule.run_pending()
            time.sleep(60)
        return

    if args.backfill:
        run_pipeline("backfill", args.since or BACKFILL_SINCE)
    else:
        run_pipeline("weekly", args.since)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Borrar el writer de Supabase**

```bash
git rm pipeline/supabase_writer.py
```

- [ ] **Step 3: Corregir `.env.example`**

Reemplazar el bloque de Supabase y el de Anthropic por:

```
# DeepSeek (motor de clasificación)
DEEPSEEK_API_KEY=sk-xxxxxxxx
```

Y borrar las líneas `SUPABASE_URL` y `SUPABASE_KEY`.

- [ ] **Step 4: Verificar que la CLI carga**

Run: `python main.py --help`
Expected: muestra las 6 opciones sin error de import.

Run: `python -m pytest -v`
Expected: PASS — 41 tests

- [ ] **Step 5: Ejecutar el seed real (sin gastar en APIs)**

```bash
PYTHONIOENCODING=utf-8 python main.py --seed-excel avianca_mentions_2026-06-05.xlsx
```

Expected: `raw` cercano a 383 (las filas sin texto se saltan), un `filtered` significativo (las ~63 de rehlat más las descartadas por idioma/keyword), e `inserted` igual a `raw - filtered`. Correrlo una segunda vez debe dar `inserted: 0` — es la prueba de que el dedup por fingerprint funciona sobre datos reales.

- [ ] **Step 6: Reclasificar el seed (primer gasto real de LLM, ~39 batches)**

```bash
PYTHONIOENCODING=utf-8 python main.py --classify
```

Expected: `clasificadas` cercano al total insertado, `fallidas` en 0 o cerca. Verificar los drivers:

```bash
PYTHONIOENCODING=utf-8 python -c "
from store import db
conn = db.connect()
for r in conn.execute('''SELECT complaint_driver, COUNT(*) c FROM mentions
                         WHERE is_complaint = 1 GROUP BY 1 ORDER BY c DESC'''):
    print(dict(r))
"
```

Expected: una distribución con varios drivers poblados. Si todo cae en `otro`, revisar el prompt antes de seguir.

- [ ] **Step 7: Commit**

```bash
git add main.py .env.example
git commit -m "feat: CLI con backfill, seed y clasificación; elimina Supabase"
```

---

## Task 10: Agregaciones del dashboard

**Files:**
- Create: `dashboard/aggregate.py`, `tests/test_aggregate.py`

**Interfaces:**
- Consumes: `store.db`
- Produces: `build_payload(conn) -> dict` con exactamente estas claves de primer nivel:
  `kpis`, `timeline`, `drivers`, `driver_by_platform`, `sentiment`, `emotions`, `mentions`, `top_complaints`, `data_quality`

**Reglas de exclusión (spec §8):**
- El `timeline` usa **solo** menciones con `date_confidence != 'unknown'`.
- Los promedios de `sentiment` usan **solo** menciones con `classification_status == 'classified'`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_aggregate.py`:

```python
from dashboard import aggregate
from store import db


def _m(idx, **kw):
    base = {
        "id": f"m-{idx}",
        "platform": "tiktok",
        "source_url": f"https://x.com/{idx}",
        "text": f"Avianca comentario numero {idx} sobre el servicio",
        "author": "user",
        "published_at": "2026-05-01T10:00:00+00:00",
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10, "shares": 1, "comments_count": 2,
        "sentiment_positive": 0.1, "sentiment_negative": 0.8,
        "sentiment_neutral": 0.1, "emotion": "anger",
        "is_complaint": 1, "complaint_driver": "equipaje",
        "classification_status": "classified",
        "raw": {}, "fetched_at": "2026-08-19T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _seed(conn, mentions):
    run_id = db.start_run(conn, "seed", None)
    db.upsert_mentions(conn, mentions, run_id)


def test_kpis_basicos(tmp_db):
    _seed(tmp_db, [_m(1), _m(2, is_complaint=0, complaint_driver=None)])
    p = aggregate.build_payload(tmp_db)
    assert p["kpis"]["total"] == 2
    assert p["kpis"]["complaints"] == 1
    assert p["kpis"]["complaint_rate"] == 50.0


def test_timeline_excluye_fechas_desconocidas(tmp_db):
    _seed(tmp_db, [
        _m(1),
        _m(2, published_at=None, date_confidence="unknown"),
    ])
    p = aggregate.build_payload(tmp_db)
    fechas = [punto["date"] for punto in p["timeline"]]
    assert fechas == ["2026-05-01"]
    assert p["timeline"][0]["counts"]["tiktok"] == 1


def test_sentiment_excluye_unclassified(tmp_db):
    _seed(tmp_db, [
        _m(1, sentiment_negative=1.0, sentiment_positive=0.0, sentiment_neutral=0.0),
        _m(2, classification_status="unclassified",
           sentiment_negative=None, sentiment_positive=None, sentiment_neutral=None),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["sentiment"]["negative"] == 100.0
    assert p["sentiment"]["classified_count"] == 1


def test_drivers_ordenados_por_volumen(tmp_db):
    _seed(tmp_db, [
        _m(1, complaint_driver="equipaje"),
        _m(2, complaint_driver="equipaje"),
        _m(3, complaint_driver="demora"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["drivers"][0]["driver"] == "equipaje"
    assert p["drivers"][0]["count"] == 2
    assert p["drivers"][1]["driver"] == "demora"


def test_driver_por_plataforma(tmp_db):
    _seed(tmp_db, [
        _m(1, platform="tiktok", complaint_driver="equipaje"),
        _m(2, platform="instagram", complaint_driver="equipaje"),
    ])
    p = aggregate.build_payload(tmp_db)
    celda = [c for c in p["driver_by_platform"]
             if c["driver"] == "equipaje" and c["platform"] == "instagram"]
    assert celda[0]["count"] == 1


def test_top_complaints_ordenadas_por_engagement(tmp_db):
    _seed(tmp_db, [
        _m(1, likes=5, shares=0, comments_count=0),
        _m(2, likes=500, shares=100, comments_count=50),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["top_complaints"][0]["engagement"] == 650
    assert p["top_complaints"][0]["id"] == "m-2"


def test_data_quality_reporta_huecos(tmp_db):
    _seed(tmp_db, [
        _m(1),
        _m(2, published_at=None, date_confidence="unknown"),
        _m(3, classification_status="unclassified"),
    ])
    p = aggregate.build_payload(tmp_db)
    assert p["data_quality"]["unknown_date"] == 1
    assert p["data_quality"]["unclassified"] == 1
    assert p["data_quality"]["total"] == 3


def test_mentions_incluye_todo_para_la_tabla(tmp_db):
    _seed(tmp_db, [_m(1), _m(2)])
    p = aggregate.build_payload(tmp_db)
    assert len(p["mentions"]) == 2
    assert set(p["mentions"][0]) >= {
        "id", "platform", "text", "author", "published_at",
        "source_url", "complaint_driver", "is_complaint", "engagement",
    }
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_aggregate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.aggregate'`

- [ ] **Step 3: Crear `dashboard/__init__.py` (vacío) e implementar `dashboard/aggregate.py`**

```python
"""
Agregaciones para el dashboard. Lee la DB y produce el payload JSON.

Sin HTML, sin red. Dos reglas de exclusión que no se negocian:
  - El timeline ignora las menciones con date_confidence 'unknown'.
    Meterlas falsearía la serie temporal, que es justo lo que pasó en v1.
  - Los promedios de sentiment ignoran las 'unclassified'. Contarlas
    como neutral inventaría neutralidad que nadie midió.
"""
import collections

from store import db

PLATFORMS = ["web", "instagram", "tiktok"]


def _engagement(m: dict) -> int:
    return (m.get("likes") or 0) + (m.get("shares") or 0) + (m.get("comments_count") or 0)


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def build_payload(conn) -> dict:
    mentions = db.all_mentions(conn)
    total = len(mentions)

    complaints = [m for m in mentions if m["is_complaint"]]
    classified = [m for m in mentions if m["classification_status"] == "classified"]
    dated = [m for m in mentions if m["date_confidence"] != "unknown" and m["published_at"]]

    # ── KPIs
    if classified:
        pos = sum(m["sentiment_positive"] or 0 for m in classified) / len(classified)
        neg = sum(m["sentiment_negative"] or 0 for m in classified) / len(classified)
        neu = sum(m["sentiment_neutral"] or 0 for m in classified) / len(classified)
    else:
        pos = neg = 0.0
        neu = 1.0

    fechas = sorted(m["published_at"][:10] for m in dated)

    kpis = {
        "total": total,
        "complaints": len(complaints),
        "complaint_rate": _pct(len(complaints), total),
        "net_sentiment": round((pos - neg) * 100, 1),
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
        "engagement": _engagement(m),
    } for m in mentions]

    top_complaints = sorted(
        [f for f in filas if f["is_complaint"]],
        key=lambda f: f["engagement"],
        reverse=True,
    )[:20]

    # ── Calidad de datos
    por_plataforma = collections.Counter(m["platform"] for m in mentions)
    cobertura_mes = collections.Counter(m["published_at"][:7] for m in dated)

    runs = [dict(r) for r in conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT 10"
    ).fetchall()]

    data_quality = {
        "total": total,
        "unknown_date": sum(1 for m in mentions if m["date_confidence"] == "unknown"),
        "unclassified": sum(1 for m in mentions
                            if m["classification_status"] == "unclassified"),
        "filtered_total": sum(r["filtered_count"] or 0 for r in runs),
        "by_platform": dict(por_plataforma),
        "by_month": dict(sorted(cobertura_mes.items())),
        "missing_sources": ["twitter"],
    }

    return {
        "kpis": kpis,
        "timeline": timeline,
        "drivers": drivers,
        "driver_by_platform": driver_by_platform,
        "driver_trend": driver_trend,
        "sentiment": {
            "positive": round(pos * 100, 1),
            "negative": round(neg * 100, 1),
            "neutral": round(neu * 100, 1),
            "classified_count": len(classified),
        },
        "emotions": emotions,
        "mentions": filas,
        "top_complaints": top_complaints,
        "data_quality": data_quality,
    }
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_aggregate.py -v`
Expected: PASS — 8 tests

- [ ] **Step 5: Commit**

```bash
git add dashboard/__init__.py dashboard/aggregate.py tests/test_aggregate.py
git commit -m "feat: agregaciones del dashboard con exclusiones de fecha y clasificación"
```

---

## Task 11: Plantilla HTML y generador

**Files:**
- Create: `dashboard/template.html`, `dashboard/build.py`, `dashboard/vendor/chart.umd.min.js`, `tests/test_build.py`
- Reference: `dashboard/index.html` (el v1 — fuente del lenguaje visual, se conserva como referencia y luego se borra)

**Interfaces:**
- Consumes: `dashboard.aggregate.build_payload`
- Produces: `render(payload: dict, template_path: str) -> str`, `build(db_path: str | None = None, out_dir: str = "dashboard") -> str` (devuelve la ruta del HTML generado)

**REQUIRED SUB-SKILLS antes de escribir la plantilla:** cargar `dataviz` (antes de escribir cualquier código de gráficos) y `frontend-design` (para la maquetación).

**Lenguaje visual a conservar de `dashboard/index.html`:** navy `#0D1117`, superficies `#161B22` / `#21262D`, naranja `#F97316`, verde `#3FB950`, rojo `#F85149`, azul `#58A6FF`, texto `#E6EDF3` / `#8B949E`; fuentes JetBrains Mono (números y etiquetas) e Inter (texto). **Corregir el `overflow: hidden` del `body`**, que impide hacer scroll.

**Los 8 bloques (spec §8):**

| # | Bloque | Nota de implementación |
|---|---|---|
| 1 | KPIs | Total · % quejas · Net Sentiment · rango de fechas · nº fuentes |
| 2 | Timeline | Área apilada por plataforma + línea de sentiment neto en eje secundario |
| 3 | Drivers de queja | Barras horizontales ordenadas + selector de mes usando `driver_trend` |
| 4 | Driver × plataforma | Heatmap en tabla HTML, intensidad por `background-color` |
| 5 | Sentiment y emociones | Dona de sentiment + barras de emociones |
| 6 | Tabla explorable | Filtros por plataforma / driver / sentimiento + búsqueda de texto, en JS puro sobre `payload.mentions` |
| 7 | Top quejas | Cards ordenadas por `engagement`, con link al original |
| 8 | Calidad de datos | `unknown_date`, `unclassified`, `filtered_total`, `by_platform`, `by_month`, y una nota explícita de que Twitter/X no está cubierto |

- [ ] **Step 1: Vendorizar Chart.js**

```bash
mkdir -p dashboard/vendor
curl -L -o dashboard/vendor/chart.umd.min.js https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js
```

Verificar que pesa más de 100 KB: `ls -l dashboard/vendor/chart.umd.min.js`

- [ ] **Step 2: Escribir el test que falla**

Crear `tests/test_build.py`:

```python
import json

from dashboard import build


PAYLOAD = {
    "kpis": {"total": 2, "complaints": 1, "complaint_rate": 50.0,
             "net_sentiment": -70.0, "date_from": "2026-05-01",
             "date_to": "2026-05-02", "sources": 1},
    "timeline": [], "drivers": [], "driver_by_platform": [],
    "driver_trend": [],
    "sentiment": {"positive": 10.0, "negative": 80.0, "neutral": 10.0,
                  "classified_count": 2},
    "emotions": {"anger": 2}, "mentions": [], "top_complaints": [],
    "data_quality": {"total": 2, "unknown_date": 0, "unclassified": 0,
                     "filtered_total": 0, "by_platform": {"tiktok": 2},
                     "by_month": {"2026-05": 2}, "missing_sources": ["twitter"]},
}


def test_render_inyecta_el_payload(tmp_path):
    plantilla = tmp_path / "t.html"
    plantilla.write_text(
        "<html><script>const DATA = __DASHBOARD_DATA__;</script></html>",
        encoding="utf-8",
    )
    html = build.render(PAYLOAD, str(plantilla))
    assert "__DASHBOARD_DATA__" not in html
    assert '"total": 2' in html or '"total":2' in html


def test_render_escapa_cierres_de_script(tmp_path):
    """Un texto con </script> dentro rompería el HTML si no se escapa."""
    plantilla = tmp_path / "t.html"
    plantilla.write_text("<script>const DATA = __DASHBOARD_DATA__;</script>",
                         encoding="utf-8")
    payload = {**PAYLOAD, "mentions": [{"text": "algo </script> malicioso"}]}
    html = build.render(payload, str(plantilla))
    assert "</script> malicioso" not in html
    assert "<\\/script>" in html


def test_render_produce_json_valido(tmp_path):
    plantilla = tmp_path / "t.html"
    plantilla.write_text("__DASHBOARD_DATA__", encoding="utf-8")
    html = build.render(PAYLOAD, str(plantilla))
    assert json.loads(html)["kpis"]["total"] == 2


def test_build_escribe_archivo_con_fecha(tmp_path, tmp_db):
    out = build.build(conn=tmp_db, out_dir=str(tmp_path))
    assert out.endswith(".html")
    assert "avianca_dashboard_" in out
    contenido = open(out, encoding="utf-8").read()
    assert "__DASHBOARD_DATA__" not in contenido
    assert "Chart" in contenido  # chart.js quedó inline
```

- [ ] **Step 3: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.build'`

- [ ] **Step 4: Implementar `dashboard/build.py`**

```python
"""
Genera el dashboard HTML autocontenido.

Un solo archivo: Chart.js inline y la data inyectada como JSON.
Abre con doble clic, funciona sin internet, se manda por correo.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from dashboard.aggregate import build_payload
from store import db

TEMPLATE = Path(__file__).parent / "template.html"
VENDOR = Path(__file__).parent / "vendor" / "chart.umd.min.js"

DATA_MARKER = "__DASHBOARD_DATA__"
VENDOR_MARKER = "__CHARTJS__"


def render(payload: dict, template_path: str = str(TEMPLATE)) -> str:
    html = Path(template_path).read_text(encoding="utf-8")

    # Escapar </script> — un comentario que lo contenga rompería el HTML.
    data = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    html = html.replace(DATA_MARKER, data)

    if VENDOR_MARKER in html:
        html = html.replace(VENDOR_MARKER, VENDOR.read_text(encoding="utf-8"))

    return html


def build(db_path: str | None = None, out_dir: str = "dashboard", conn=None) -> str:
    own_conn = conn is None
    if own_conn:
        conn = db.connect(db_path) if db_path else db.connect()

    try:
        payload = build_payload(conn)
    finally:
        if own_conn:
            conn.close()

    html = render(payload)

    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = Path(out_dir) / f"avianca_dashboard_{fecha}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"[Dashboard] {out_path}  ({payload['kpis']['total']} menciones)")
    return str(out_path)


if __name__ == "__main__":
    build()
```

- [ ] **Step 5: Escribir `dashboard/template.html`**

Cargar primero los skills `dataviz` y `frontend-design`. Partir de este esqueleto,
que fija el contrato de marcadores y el cableado de datos; el trabajo de los skills
es el acabado visual de cada bloque, no cambiar esta estructura.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Avianca — Social Listening</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --navy:#0D1117; --navy-2:#161B22; --navy-3:#21262D; --navy-4:#30363D;
    --orange:#F97316; --green:#3FB950; --red:#F85149; --blue:#58A6FF;
    --txt:#E6EDF3; --txt-2:#8B949E; --txt-3:#484F58;
    --border:rgba(48,54,61,.9);
    /* Fallbacks explícitos: el HTML debe verse bien sin internet */
    --mono:'JetBrains Mono',ui-monospace,Consolas,monospace;
    --sans:'Inter',system-ui,-apple-system,sans-serif;
  }
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--navy);color:var(--txt);font-family:var(--sans);
       font-size:13px;overflow-x:hidden}          /* scroll vertical SÍ permitido */
  .wrap{max-width:1400px;margin:0 auto;padding:24px}
  section{margin-bottom:32px}
  h2{font-family:var(--mono);font-size:11px;letter-spacing:.18em;
     text-transform:uppercase;color:var(--orange);margin-bottom:12px}
  .card{background:var(--navy-2);border:1px solid var(--border);
        border-radius:6px;padding:16px}
  .scroll-x{overflow-x:auto}                       /* tablas y gráficos anchos */
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{padding:8px;text-align:left;border-bottom:1px solid var(--border)}
  th{font-family:var(--mono);font-size:10px;color:var(--txt-2);
     text-transform:uppercase;letter-spacing:.08em}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Avianca · Social Listening</h1>
    <p id="rango" class="muted"></p>
  </header>

  <section id="b1"><h2>Resumen</h2><div id="kpis" class="card"></div></section>
  <section id="b2"><h2>Volumen y sentimiento en el tiempo</h2>
    <div class="card scroll-x"><canvas id="chTimeline" height="90"></canvas></div></section>
  <section id="b3"><h2>¿De qué se queja la gente?</h2>
    <div class="card scroll-x"><canvas id="chDrivers" height="110"></canvas></div></section>
  <section id="b4"><h2>Driver por plataforma</h2>
    <div class="card scroll-x"><div id="heatmap"></div></div></section>
  <section id="b5"><h2>Sentimiento y emociones</h2>
    <div class="card scroll-x">
      <canvas id="chSentiment" height="120"></canvas>
      <canvas id="chEmotions" height="120"></canvas></div></section>
  <section id="b6"><h2>Todas las menciones</h2>
    <div class="card">
      <div id="filtros"></div>
      <div class="scroll-x"><table id="tabla">
        <thead><tr><th>Fecha</th><th>Plataforma</th><th>Autor</th>
          <th>Texto</th><th>Driver</th><th>Engagement</th><th>Link</th></tr></thead>
        <tbody id="tbody"></tbody></table></div>
      <p id="conteoTabla" class="muted"></p></div></section>
  <section id="b7"><h2>Quejas con más alcance</h2><div id="topQuejas"></div></section>
  <section id="b8"><h2>Calidad de los datos</h2><div id="calidad" class="card"></div></section>
</div>

<script>__CHARTJS__</script>
<script>
const DATA = __DASHBOARD_DATA__;

const PLT_COLOR = { web:'#58A6FF', instagram:'#E1306C', tiktok:'#69C9D0' };
const DRIVER_LABEL = {
  equipaje:'Equipaje', cancelacion:'Cancelaciones', demora:'Demoras',
  atencion_cliente:'Atención al cliente', cobros_tarifas:'Cobros y tarifas',
  lifemiles:'LifeMiles', asientos_comida:'Asientos y comida',
  reembolsos:'Reembolsos', otro:'Otro',
};
const EMO_LABEL = { happiness:'Felicidad', anger:'Enojo', love:'Amor',
                    sadness:'Tristeza', neutral:'Neutral' };

const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ── Bloque 1: KPIs
function renderKpis(){ /* DATA.kpis → total, complaint_rate, net_sentiment, date_from/to, sources */ }

// ── Bloque 2: timeline (área apilada + línea de sentiment en eje secundario)
function renderTimeline(){ /* DATA.timeline: [{date, counts:{web,instagram,tiktok}, net_sentiment}] */ }

// ── Bloque 3: drivers (barras horizontales) + tendencia con DATA.driver_trend
function renderDrivers(){ /* DATA.drivers: [{driver, count, pct}] */ }

// ── Bloque 4: heatmap driver × plataforma, intensidad por background-color
function renderHeatmap(){ /* DATA.driver_by_platform: [{driver, platform, count}] */ }

// ── Bloque 5: dona de sentiment + barras de emociones
function renderSentiment(){ /* DATA.sentiment, DATA.emotions */ }

// ── Bloque 6: tabla con filtros en JS puro sobre DATA.mentions
let filtros = { platform:'', driver:'', sentiment:'', q:'' };
function filtradas(){
  return DATA.mentions.filter(m =>
    (!filtros.platform || m.platform === filtros.platform) &&
    (!filtros.driver   || m.complaint_driver === filtros.driver) &&
    (!filtros.sentiment || (filtros.sentiment === 'queja' ? m.is_complaint : !m.is_complaint)) &&
    (!filtros.q || (m.text || '').toLowerCase().includes(filtros.q.toLowerCase()))
  );
}
function renderTabla(){ /* pinta filtradas() en #tbody y el conteo en #conteoTabla */ }

// ── Bloque 7: cards ordenadas por engagement
function renderTopQuejas(){ /* DATA.top_complaints */ }

// ── Bloque 8: calidad de datos — texto explícito, no solo números
function renderCalidad(){
  const q = DATA.data_quality;
  // Debe decir en palabras:
  //  - q.unknown_date menciones sin fecha confiable, EXCLUIDAS del timeline
  //  - q.unclassified sin clasificar, excluidas de los promedios de sentimiento
  //  - q.filtered_total descartadas por ruido (agregadores, otro idioma)
  //  - cobertura por plataforma (q.by_platform) y por mes (q.by_month)
  //  - que Twitter/X (q.missing_sources) NO está cubierto en esta versión
}

[renderKpis, renderTimeline, renderDrivers, renderHeatmap,
 renderSentiment, renderTabla, renderTopQuejas, renderCalidad]
  .forEach(fn => fn());
</script>
</body>
</html>
```

Requisitos que el acabado no puede romper:

- Los marcadores `__DASHBOARD_DATA__` y `__CHARTJS__` deben quedar tal cual — `build.py` los busca literalmente.
- Todo texto que venga de `DATA` se pinta con `esc()`. Son comentarios de internet.
- El `body` hace scroll vertical y nunca horizontal; lo ancho scrollea dentro de `.scroll-x`.
- Cada `font-family` conserva sus fallbacks: el archivo debe verse bien sin internet.

- [ ] **Step 6: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_build.py -v`
Expected: PASS — 4 tests

- [ ] **Step 7: Generar el dashboard real y abrirlo**

```bash
PYTHONIOENCODING=utf-8 python -m dashboard.build
```

Expected: escribe `dashboard/avianca_dashboard_<fecha>.html`. Abrirlo en el navegador y verificar visualmente:

1. Los 8 bloques renderizan sin errores en la consola del navegador.
2. La página hace scroll vertical.
3. Los filtros de la tabla (bloque 6) funcionan.
4. El bloque 8 muestra los conteos reales de calidad de datos.
5. Desconectar el wifi y recargar: debe seguir funcionando (los gráficos, al menos; las fuentes pueden degradar).

- [ ] **Step 8: Borrar el dashboard v1**

```bash
git rm dashboard/index.html
```

- [ ] **Step 9: Commit**

```bash
git add dashboard/
git commit -m "feat: dashboard HTML autocontenido con drivers de queja"
```

---

## Task 12: Backfill real y cierre

**Files:**
- Create: `README.md`
- Modify: `INSTRUCCIONES.md` (marcarlo como blueprint histórico del v1)

**Interfaces:**
- Consumes: todo
- Produces: nada de código

**Esta es la única tarea que gasta dinero en scraping.** Presupuesto estimado: $3–5 USD.

- [ ] **Step 1: Correr la suite completa antes de gastar**

Run: `python -m pytest -v`
Expected: PASS — 53 tests

- [ ] **Step 2: Backfill de 4 meses**

```bash
PYTHONIOENCODING=utf-8 python main.py --backfill --since 2026-04-19
```

Expected: reporta menciones crudas, descartadas por relevancia, insertadas, duplicadas, y clasificadas. El total acumulado en DB debe superar el del seed.

- [ ] **Step 3: Reintentar lo que haya fallado**

```bash
PYTHONIOENCODING=utf-8 python main.py --classify
```

Expected: `pendientes: 0` o un número pequeño que baje respecto a la corrida anterior.

- [ ] **Step 4: Regenerar el dashboard con los datos completos**

```bash
PYTHONIOENCODING=utf-8 python -m dashboard.build
```

Abrirlo y verificar que el timeline cubre efectivamente abril–agosto y que los drivers tienen volumen suficiente para ser interpretables.

- [ ] **Step 5: Escribir `README.md`**

Debe cubrir, en español:

- Qué hace el proyecto en dos frases.
- Requisitos: Python 3.12, `pip install -r requirements.txt`, variables de `.env` (`DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`, `APIFY_API_TOKEN`, `DEEPSEEK_API_KEY`).
- Los 6 comandos de la CLI, con una línea de explicación cada uno.
- Cómo generar el dashboard: `python -m dashboard.build`.
- Nota de Windows: usar `PYTHONIOENCODING=utf-8` para que la consola no reviente con acentos.
- Limitaciones declaradas, copiadas del spec §12: sin Twitter/X, Instagram mide solo el canal propio, cobertura desigual por mes, menciones sin fecha excluidas del timeline.

- [ ] **Step 6: Marcar `INSTRUCCIONES.md` como histórico**

Añadir al inicio del archivo:

```markdown
> ⚠️ **Documento histórico.** Este es el blueprint del pipeline v1 (junio 2026).
> El sistema actual es el v2: ver [README.md](README.md) y
> [el diseño de v2](docs/superpowers/specs/2026-08-19-avianca-sentiment-4meses-design.md).
> Diferencias principales: v2 usa SQLite en vez de Supabase, clasifica drivers
> de queja, y no incluye Twitter/X.
```

- [ ] **Step 7: Commit final**

```bash
git add README.md INSTRUCCIONES.md
git commit -m "docs: README de v2 y marca de histórico en el blueprint v1"
```

---

## Resumen de verificación

Al terminar las 12 tareas, esto debe ser cierto:

| Verificación | Comando |
|---|---|
| 53 tests en verde | `python -m pytest -v` |
| Ningún test toca la red | `grep -rn "requests.post\|ApifyClient" tests/` → solo dentro de `patch(...)` |
| La DB acumula | `python -c "from store import db; print(db.connect().execute('SELECT COUNT(*) FROM mentions').fetchone()[0])"` |
| Correr dos veces no duplica | `python main.py --seed-excel <x>.xlsx` dos veces → `inserted: 0` la segunda |
| Ninguna fecha inventada | `SELECT COUNT(*) FROM mentions WHERE published_at = fetched_at` → 0 |
| Toda queja tiene driver | `SELECT COUNT(*) FROM mentions WHERE is_complaint=1 AND complaint_driver IS NULL` → 0 |
| Supabase eliminado | `grep -rn "supabase" --include=*.py .` → sin resultados |
| El dashboard abre offline | Desconectar wifi, abrir el HTML generado |
