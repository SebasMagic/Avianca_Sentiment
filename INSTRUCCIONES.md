> ⚠️ **Documento histórico.** Este es el blueprint del pipeline v1 (junio 2026).
> El sistema actual es el v2: ver [README.md](README.md) y
> [el diseño de v2](docs/superpowers/specs/2026-08-19-avianca-sentiment-4meses-design.md).
> Diferencias principales: v2 usa SQLite en vez de Supabase, clasifica drivers
> de queja, y no incluye Twitter/X.

# Avianca Colombia — Brand Sentiment Monitor
## Instrucciones para Claude Code

> Este documento es el blueprint completo del proyecto. Léelo entero antes de escribir una sola línea de código. Construye los archivos en el orden indicado.

---

## 🎯 Qué construimos

Un pipeline automatizado que:
1. Extrae menciones de **Avianca** en Colombia desde 4 fuentes (DataForSEO, Instagram, TikTok, Twitter/X)
2. Normaliza todos los datos a un **schema unificado**
3. Corre **sentiment analysis** (DataForSEO nativo para web; Claude API para redes sociales)
4. Guarda en **Supabase**
5. Expone un **dashboard HTML** con gauge de sentiment, timeline y top menciones negativas

---

## 📁 Estructura de archivos a crear

```
avianca-sentiment/
├── INSTRUCCIONES.md          ← este archivo
├── config.py                 ← todas las keys y constantes
├── scrapers/
│   ├── __init__.py
│   ├── dataforseo_scraper.py
│   ├── apify_instagram.py
│   ├── apify_tiktok.py
│   └── apify_twitter.py
├── pipeline/
│   ├── __init__.py
│   ├── normalizer.py
│   ├── sentiment_engine.py
│   └── supabase_writer.py
├── dashboard/
│   └── index.html
├── main.py                   ← entry point que orquesta todo
├── requirements.txt
└── .env.example
```

---

## ⚙️ PASO 1 — Crear `requirements.txt`

```txt
requests==2.31.0
python-dotenv==1.0.0
supabase==2.4.0
anthropic==0.25.0
apify-client==1.6.4
schedule==1.2.1
python-dateutil==2.9.0
```

---

## ⚙️ PASO 2 — Crear `.env.example`

```env
# DataForSEO
DATAFORSEO_LOGIN=tu_email@ejemplo.com
DATAFORSEO_PASSWORD=tu_password

# Apify
APIFY_API_TOKEN=apify_api_xxxxxxxxxxxxxxxx

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJxxxxxxxxxx

# Anthropic (Claude API para sentiment de redes sociales)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx

# Config del proyecto
BRAND_KEYWORD=Avianca
COUNTRY_CODE=CO
LANGUAGE_CODE=es
LOCATION_CODE=2170
```

---

## ⚙️ PASO 3 — Crear `config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

# DataForSEO
DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")

# Apify
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Proyecto
BRAND_KEYWORD = os.getenv("BRAND_KEYWORD", "Avianca")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "CO")
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "es")
LOCATION_CODE = int(os.getenv("LOCATION_CODE", "2170"))  # Colombia en DataForSEO

# Apify actor IDs (no cambiar)
APIFY_INSTAGRAM_ACTOR = "apify/instagram-scraper"
APIFY_TIKTOK_ACTOR = "clockworks/tiktok-scraper"
APIFY_TWITTER_ACTOR = "apidojo/tweet-scraper"

# Límites por scraper por ejecución
LIMIT_DATAFORSEO = 100
LIMIT_INSTAGRAM = 50
LIMIT_TIKTOK = 50
LIMIT_TWITTER = 100
```

---

## ⚙️ PASO 4 — Schema unificado (referencia para todos los módulos)

**Todos los scrapers deben retornar una lista de dicts con exactamente este schema:**

```python
{
    "id": str,                    # uuid generado localmente (uuid4)
    "platform": str,              # "web" | "instagram" | "tiktok" | "twitter"
    "source_url": str,            # URL de la mención
    "text": str,                  # caption / tweet / snippet de texto
    "author": str | None,         # username o nombre del autor
    "published_at": str,          # ISO 8601: "2025-06-01T12:00:00Z"
    "country": str,               # "CO"
    "likes": int,                 # 0 si no aplica
    "shares": int,                # 0 si no aplica
    "comments_count": int,        # 0 si no aplica
    # Sentiment — se llena en sentiment_engine.py, NO en el scraper
    "sentiment_positive": float,  # 0.0 a 1.0
    "sentiment_negative": float,  # 0.0 a 1.0
    "sentiment_neutral": float,   # 0.0 a 1.0
    "emotion": str,               # "happiness"|"anger"|"love"|"sadness"|"neutral"
    # Metadata
    "raw": dict,                  # objeto original completo sin modificar
    "fetched_at": str,            # ISO 8601 del momento de extracción
}
```

---

## ⚙️ PASO 5 — Crear `scrapers/dataforseo_scraper.py`

**Qué hace:** Consulta el endpoint `/v3/content_analysis/search/live` de DataForSEO.
El sentiment ya viene en el response — no necesita pasar por `sentiment_engine.py`.

```python
"""
DataForSEO Content Analysis scraper.
Retorna menciones web/blogs/Reddit con sentiment nativo incluido.
"""
import uuid
import requests
from base64 import b64encode
from datetime import datetime, timezone
from config import (
    DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD,
    BRAND_KEYWORD, LANGUAGE_CODE, LIMIT_DATAFORSEO
)


def _get_headers():
    credentials = b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json"
    }


def scrape() -> list[dict]:
    """
    Consulta DataForSEO y retorna lista de menciones normalizadas.
    El sentiment viene nativo del API (positive/negative/neutral + emotion).
    """
    payload = [{
        "keyword": BRAND_KEYWORD,
        "language_code": LANGUAGE_CODE,
        "filters": [
            ["country_iso_code", "=", "CO"]
        ],
        "order_by": ["sentiment_connotations.negative,desc"],
        "limit": LIMIT_DATAFORSEO
    }]

    response = requests.post(
        "https://api.dataforseo.com/v3/content_analysis/search/live",
        headers=_get_headers(),
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    data = response.json()

    results = []
    try:
        items = data["tasks"][0]["result"][0]["items"]
    except (KeyError, IndexError, TypeError):
        print("[DataForSEO] No items in response")
        return []

    fetched_at = datetime.now(timezone.utc).isoformat()

    for item in items:
        # Extraer sentiment nativo
        conn = item.get("connotation_types", {}) or {}
        sent_conns = item.get("sentiment_connotations", {}) or {}

        # Determinar emoción dominante
        emotion_map = {
            "anger": sent_conns.get("anger", 0) or 0,
            "happiness": sent_conns.get("happiness", 0) or 0,
            "love": sent_conns.get("love", 0) or 0,
            "sadness": sent_conns.get("sadness", 0) or 0,
        }
        dominant_emotion = max(emotion_map, key=emotion_map.get)
        if emotion_map[dominant_emotion] == 0:
            dominant_emotion = "neutral"

        # Extraer texto principal
        content_info = item.get("content_info", {}) or {}
        text = content_info.get("snippet", "") or item.get("title", "") or ""

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "web",
            "source_url": item.get("url", ""),
            "text": text,
            "author": item.get("domain", None),
            "published_at": item.get("date_published", fetched_at),
            "country": "CO",
            "likes": 0,
            "shares": 0,
            "comments_count": 0,
            # Sentiment nativo DataForSEO
            "sentiment_positive": conn.get("positive", 0.0) or 0.0,
            "sentiment_negative": conn.get("negative", 0.0) or 0.0,
            "sentiment_neutral": conn.get("neutral", 1.0) or 1.0,
            "emotion": dominant_emotion,
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[DataForSEO] {len(results)} menciones extraídas")
    return results
```

---

## ⚙️ PASO 6 — Crear `scrapers/apify_instagram.py`

**Qué hace:** Corre el actor `apify/instagram-scraper` buscando menciones de Avianca en Colombia.
**Nota:** El sentiment NO viene aquí — se llena en `sentiment_engine.py` después.

```python
"""
Apify Instagram scraper.
Extrae posts públicos que mencionan Avianca en Colombia.
Sentiment se procesa después en sentiment_engine.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import APIFY_API_TOKEN, APIFY_INSTAGRAM_ACTOR, BRAND_KEYWORD, LIMIT_INSTAGRAM


def scrape() -> list[dict]:
    """
    Retorna lista de posts de Instagram normalizados (sin sentiment aún).
    """
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "search": BRAND_KEYWORD,
        "searchType": "hashtag",
        "resultsLimit": LIMIT_INSTAGRAM,
        "addParentData": False,
    }

    print(f"[Instagram] Iniciando actor {APIFY_INSTAGRAM_ACTOR}...")
    run = client.actor(APIFY_INSTAGRAM_ACTOR).call(run_input=run_input)

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []

    for item in items:
        # Intentar obtener texto del post
        text = (
            item.get("caption", "")
            or item.get("alt", "")
            or item.get("accessibility_caption", "")
            or ""
        )

        # Solo incluir si menciona la marca
        if BRAND_KEYWORD.lower() not in text.lower() and BRAND_KEYWORD.lower() not in str(item.get("hashtags", [])).lower():
            continue

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "instagram",
            "source_url": item.get("url", item.get("shortCode", "")),
            "text": text,
            "author": item.get("ownerUsername", None),
            "published_at": item.get("timestamp", fetched_at),
            "country": "CO",
            "likes": item.get("likesCount", 0) or 0,
            "shares": 0,
            "comments_count": item.get("commentsCount", 0) or 0,
            # Sentiment vacío — se llena en sentiment_engine.py
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[Instagram] {len(results)} posts extraídos")
    return results
```

---

## ⚙️ PASO 7 — Crear `scrapers/apify_tiktok.py`

**Qué hace:** Corre `clockworks/tiktok-scraper` buscando videos con #avianca o mención de Avianca.

```python
"""
Apify TikTok scraper.
Extrae videos que mencionan Avianca en Colombia.
Sentiment se procesa después en sentiment_engine.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import APIFY_API_TOKEN, APIFY_TIKTOK_ACTOR, BRAND_KEYWORD, LIMIT_TIKTOK


def scrape() -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "hashtags": [BRAND_KEYWORD.lower(), f"{BRAND_KEYWORD.lower()}colombia"],
        "resultsPerPage": LIMIT_TIKTOK,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }

    print(f"[TikTok] Iniciando actor {APIFY_TIKTOK_ACTOR}...")
    run = client.actor(APIFY_TIKTOK_ACTOR).call(run_input=run_input)

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []

    for item in items:
        text = item.get("text", "") or item.get("description", "") or ""
        author_meta = item.get("authorMeta", {}) or {}

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "tiktok",
            "source_url": item.get("webVideoUrl", item.get("id", "")),
            "text": text,
            "author": author_meta.get("name", None),
            "published_at": item.get("createTimeISO", fetched_at),
            "country": "CO",
            "likes": item.get("diggCount", 0) or 0,
            "shares": item.get("shareCount", 0) or 0,
            "comments_count": item.get("commentCount", 0) or 0,
            # Sentiment vacío — se llena en sentiment_engine.py
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[TikTok] {len(results)} videos extraídos")
    return results
```

---

## ⚙️ PASO 8 — Crear `scrapers/apify_twitter.py`

**Qué hace:** Corre `apidojo/tweet-scraper` buscando tweets que mencionan Avianca en Colombia.

```python
"""
Apify Twitter/X scraper.
Extrae tweets que mencionan Avianca en Colombia.
Sentiment se procesa después en sentiment_engine.py.
"""
import uuid
from datetime import datetime, timezone
from apify_client import ApifyClient
from config import APIFY_API_TOKEN, APIFY_TWITTER_ACTOR, BRAND_KEYWORD, LIMIT_TWITTER


def scrape() -> list[dict]:
    client = ApifyClient(APIFY_API_TOKEN)

    # Query para Colombia: menciones + geolocalización implícita por idioma
    search_query = f"{BRAND_KEYWORD} lang:es -is:retweet"

    run_input = {
        "searchTerms": [search_query],
        "maxItems": LIMIT_TWITTER,
        "sort": "Latest",
        "twitterContent": "Latest",
    }

    print(f"[Twitter] Iniciando actor {APIFY_TWITTER_ACTOR}...")
    run = client.actor(APIFY_TWITTER_ACTOR).call(run_input=run_input)

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []

    for item in items:
        text = item.get("text", "") or item.get("full_text", "") or ""
        author = item.get("author", {}) or {}

        results.append({
            "id": str(uuid.uuid4()),
            "platform": "twitter",
            "source_url": item.get("url", ""),
            "text": text,
            "author": author.get("userName", None),
            "published_at": item.get("createdAt", fetched_at),
            "country": "CO",
            "likes": item.get("likeCount", 0) or 0,
            "shares": item.get("retweetCount", 0) or 0,
            "comments_count": item.get("replyCount", 0) or 0,
            # Sentiment vacío — se llena en sentiment_engine.py
            "sentiment_positive": 0.0,
            "sentiment_negative": 0.0,
            "sentiment_neutral": 1.0,
            "emotion": "neutral",
            "raw": item,
            "fetched_at": fetched_at,
        })

    print(f"[Twitter] {len(results)} tweets extraídos")
    return results
```

---

## ⚙️ PASO 9 — Crear `pipeline/sentiment_engine.py`

**Qué hace:** Recibe menciones de redes sociales (Instagram, TikTok, Twitter) sin sentiment
y las clasifica usando Claude API. Las menciones de web ya vienen con sentiment de DataForSEO.

```python
"""
Sentiment engine.
- Plataforma "web": sentiment ya viene de DataForSEO, no hace nada.
- Plataformas "instagram", "tiktok", "twitter": usa Claude API para clasificar.
Procesa en batches de 10 para minimizar llamadas a la API.
"""
import json
import anthropic
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Eres un analizador de sentiment especializado en menciones de marca en español latinoamericano.
Dado un texto, retorna ÚNICAMENTE un JSON con este formato exacto, sin explicaciones adicionales:
{
  "sentiment_positive": 0.0,
  "sentiment_negative": 0.0,
  "sentiment_neutral": 1.0,
  "emotion": "happiness"
}
Reglas:
- Los tres valores de sentiment deben sumar 1.0
- emotion debe ser exactamente uno de: "happiness", "anger", "love", "sadness", "neutral"
- Contexto: el texto es una mención de la aerolínea Avianca en Colombia
- Sé preciso con el español coloquial colombiano"""


def _analyze_batch(texts: list[str]) -> list[dict]:
    """Analiza un batch de textos y retorna lista de sentiments."""
    prompt = f"""Analiza el sentiment de cada uno de los siguientes {len(texts)} textos sobre Avianca.
Retorna un array JSON con exactamente {len(texts)} objetos en el mismo orden.
No incluyas texto antes o después del JSON.

Textos:
{json.dumps(texts, ensure_ascii=False, indent=2)}

Responde SOLO con el array JSON:"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # Limpiar si viene con markdown
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


def enrich_sentiment(mentions: list[dict]) -> list[dict]:
    """
    Enriquece menciones de redes sociales con sentiment de Claude.
    Las menciones web ya tienen sentiment de DataForSEO y se pasan sin cambios.
    """
    web_mentions = [m for m in mentions if m["platform"] == "web"]
    social_mentions = [m for m in mentions if m["platform"] != "web"]

    if not social_mentions:
        return mentions

    print(f"[Sentiment] Analizando {len(social_mentions)} menciones de redes sociales...")

    # Procesar en batches de 10
    batch_size = 10
    enriched = []

    for i in range(0, len(social_mentions), batch_size):
        batch = social_mentions[i:i + batch_size]
        texts = [m["text"] for m in batch]

        try:
            sentiments = _analyze_batch(texts)
            for mention, sentiment in zip(batch, sentiments):
                mention.update({
                    "sentiment_positive": float(sentiment.get("sentiment_positive", 0.0)),
                    "sentiment_negative": float(sentiment.get("sentiment_negative", 0.0)),
                    "sentiment_neutral": float(sentiment.get("sentiment_neutral", 1.0)),
                    "emotion": sentiment.get("emotion", "neutral"),
                })
                enriched.append(mention)
        except Exception as e:
            print(f"[Sentiment] Error en batch {i//batch_size + 1}: {e}")
            # Si falla el batch, dejar como neutral
            enriched.extend(batch)

    print(f"[Sentiment] Completado: {len(enriched)} menciones enriquecidas")
    return web_mentions + enriched
```

---

## ⚙️ PASO 10 — Crear `pipeline/supabase_writer.py`

**Qué hace:** Inserta las menciones en Supabase. Primero crea las tablas si no existen.

```python
"""
Supabase writer.
Inserta menciones normalizadas en la tabla brand_mentions.
Usa upsert para evitar duplicados por source_url + platform.
"""
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def write_mentions(mentions: list[dict]) -> int:
    """
    Inserta menciones en Supabase.
    Retorna cantidad de filas insertadas.
    """
    if not mentions:
        return 0

    # Preparar datos: remover campo 'raw' para no saturar Supabase
    # (guardar raw en columna JSONB)
    rows = []
    for m in mentions:
        row = {k: v for k, v in m.items() if k != "raw"}
        row["raw"] = m.get("raw", {})  # JSONB
        rows.append(row)

    response = (
        supabase.table("brand_mentions")
        .upsert(rows, on_conflict="platform,source_url")
        .execute()
    )

    count = len(response.data) if response.data else 0
    print(f"[Supabase] {count} menciones guardadas")
    return count


def get_summary() -> dict:
    """Retorna resumen de menciones guardadas para logging."""
    result = supabase.table("brand_mentions").select("platform", count="exact").execute()
    return {"total": result.count}
```

**SQL para crear la tabla en Supabase (correr una sola vez en el SQL Editor):**

```sql
-- Tabla principal de menciones
create table if not exists brand_mentions (
  id uuid primary key,
  platform text not null,
  source_url text,
  text text,
  author text,
  published_at timestamptz,
  country text default 'CO',
  likes integer default 0,
  shares integer default 0,
  comments_count integer default 0,
  sentiment_positive float default 0.0,
  sentiment_negative float default 0.0,
  sentiment_neutral float default 1.0,
  emotion text default 'neutral',
  raw jsonb,
  fetched_at timestamptz default now(),
  -- Constraint para evitar duplicados
  unique (platform, source_url)
);

-- Índices para el dashboard
create index if not exists idx_brand_mentions_platform on brand_mentions(platform);
create index if not exists idx_brand_mentions_published_at on brand_mentions(published_at desc);
create index if not exists idx_brand_mentions_sentiment_negative on brand_mentions(sentiment_negative desc);
create index if not exists idx_brand_mentions_emotion on brand_mentions(emotion);
create index if not exists idx_brand_mentions_fetched_at on brand_mentions(fetched_at desc);

-- Vista para el dashboard: sentiment diario por plataforma
create or replace view sentiment_daily as
select
  date_trunc('day', published_at) as date,
  platform,
  count(*) as total_mentions,
  round(avg(sentiment_positive)::numeric, 3) as avg_positive,
  round(avg(sentiment_negative)::numeric, 3) as avg_negative,
  round(avg(sentiment_neutral)::numeric, 3) as avg_neutral,
  mode() within group (order by emotion) as top_emotion
from brand_mentions
group by 1, 2
order by 1 desc, 2;
```

---

## ⚙️ PASO 11 — Crear `pipeline/normalizer.py`

**Qué hace:** Valida y limpia el schema antes de escribir a Supabase.

```python
"""
Normalizer: valida y limpia el schema unificado.
Filtra menciones sin texto o con texto demasiado corto.
"""
from datetime import datetime, timezone


def normalize(mentions: list[dict]) -> list[dict]:
    """
    Limpia y valida la lista de menciones.
    - Filtra textos vacíos o menores a 10 caracteres
    - Asegura tipos correctos
    - Valida que sentiment sume ~1.0
    """
    clean = []
    for m in mentions:
        text = (m.get("text") or "").strip()
        if len(text) < 10:
            continue

        # Validar sentiment
        pos = float(m.get("sentiment_positive", 0.0))
        neg = float(m.get("sentiment_negative", 0.0))
        neu = float(m.get("sentiment_neutral", 1.0))
        total = pos + neg + neu
        if total > 0 and abs(total - 1.0) > 0.05:
            # Normalizar si la suma está desviada
            pos, neg, neu = pos/total, neg/total, neu/total

        # Asegurar published_at válido
        pub = m.get("published_at")
        if not pub:
            pub = datetime.now(timezone.utc).isoformat()

        clean.append({
            **m,
            "text": text,
            "sentiment_positive": round(pos, 4),
            "sentiment_negative": round(neg, 4),
            "sentiment_neutral": round(neu, 4),
            "likes": int(m.get("likes", 0) or 0),
            "shares": int(m.get("shares", 0) or 0),
            "comments_count": int(m.get("comments_count", 0) or 0),
            "published_at": pub,
        })

    print(f"[Normalizer] {len(clean)}/{len(mentions)} menciones válidas")
    return clean
```

---

## ⚙️ PASO 12 — Crear `main.py`

**Qué hace:** Orquesta todo el pipeline de principio a fin.

```python
"""
main.py — Entry point del pipeline Avianca Sentiment Monitor.

Uso:
  python main.py              → corre pipeline una vez ahora
  python main.py --schedule   → corre cada lunes a las 8am (Colombia)
"""
import sys
import schedule
import time
from datetime import datetime, timezone

from scrapers import dataforseo_scraper, apify_instagram, apify_tiktok, apify_twitter
from pipeline.normalizer import normalize
from pipeline.sentiment_engine import enrich_sentiment
from pipeline.supabase_writer import write_mentions, get_summary


def run_pipeline():
    print(f"\n{'='*50}")
    print(f"[Pipeline] Iniciando: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*50}\n")

    all_mentions = []

    # 1. Scrapers en paralelo (sequential por simplicidad)
    scrapers = [
        ("DataForSEO", dataforseo_scraper.scrape),
        ("Instagram",  apify_instagram.scrape),
        ("TikTok",     apify_tiktok.scrape),
        ("Twitter",    apify_twitter.scrape),
    ]

    for name, scrape_fn in scrapers:
        try:
            mentions = scrape_fn()
            all_mentions.extend(mentions)
        except Exception as e:
            print(f"[{name}] ERROR: {e}")

    print(f"\n[Pipeline] Total raw: {len(all_mentions)} menciones\n")

    # 2. Normalizar
    normalized = normalize(all_mentions)

    # 3. Enricher de sentiment (solo redes sociales)
    enriched = enrich_sentiment(normalized)

    # 4. Guardar en Supabase
    saved = write_mentions(enriched)

    # 5. Resumen
    summary = get_summary()
    print(f"\n{'='*50}")
    print(f"[Pipeline] Completado: {saved} nuevas menciones guardadas")
    print(f"[Pipeline] Total en DB: {summary['total']}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    if "--schedule" in sys.argv:
        print("[Scheduler] Corriendo cada lunes a las 8am hora Colombia...")
        schedule.every().monday.at("08:00").do(run_pipeline)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_pipeline()
```

---

## ⚙️ PASO 13 — Crear `scrapers/__init__.py` y `pipeline/__init__.py`

Ambos archivos vacíos:
```python
# __init__.py
```

---

## ⚙️ PASO 14 — Dashboard `dashboard/index.html`

**Instrucciones para Claude Code al construir el dashboard:**

Crea un archivo HTML standalone (sin dependencias externas excepto Chart.js via CDN) que:

1. **Se conecta a Supabase** usando la REST API (no el SDK) via fetch con las variables de entorno hardcodeadas como constantes JS en la parte superior del archivo
2. **Muestra 4 secciones:**
   - **Header**: nombre de marca + fecha del último update + badge de sentiment general (verde/rojo)
   - **Gauge**: donut Chart.js con % positivo / negativo / neutral
   - **Timeline**: line chart de menciones por día, con una línea por plataforma (web, instagram, tiktok, twitter)
   - **Top negativas**: tabla de las 10 menciones con mayor `sentiment_negative`, con columnas: plataforma, autor, texto (truncado 80 chars), score negativo, fecha
3. **Paleta**: dark navy (#0D1117) + naranja (#F97316) como acento — consistente con el design system de MagicHack
4. **Auto-refresh** cada 5 minutos via `setInterval`
5. **Fuente**: JetBrains Mono para datos/números, Inter para labels

---

## 🧪 PASO 15 — Testing

Antes de correr el pipeline completo, testea cada scraper individualmente:

```bash
# Test DataForSEO (el más rápido, ya tienes el key)
python -c "from scrapers import dataforseo_scraper; r = dataforseo_scraper.scrape(); print(len(r), 'menciones'); print(r[0] if r else 'vacío')"

# Test Apify Instagram
python -c "from scrapers import apify_instagram; r = apify_instagram.scrape(); print(len(r), 'posts')"

# Test sentiment engine con texto de prueba
python -c "
from pipeline.sentiment_engine import enrich_sentiment
test = [{'platform':'twitter','text':'Avianca perdió mis maletas otra vez, terrible servicio','sentiment_positive':0,'sentiment_negative':0,'sentiment_neutral':1,'emotion':'neutral'}]
result = enrich_sentiment(test)
print(result[0]['emotion'], result[0]['sentiment_negative'])
"

# Pipeline completo
python main.py
```

---

## 🔑 Checklist antes de correr

- [ ] Crear archivo `.env` basado en `.env.example` con tus keys reales
- [ ] Correr el SQL de creación de tablas en Supabase SQL Editor
- [ ] Verificar que el DATAFORSEO_LOGIN y PASSWORD son correctos
- [ ] Crear cuenta en Apify y obtener APIFY_API_TOKEN
- [ ] Verificar que ANTHROPIC_API_KEY tiene créditos disponibles
- [ ] Instalar dependencias: `pip install -r requirements.txt`

---

## 📊 Costo estimado por ejecución semanal

| Fuente | Volumen | Costo aprox. |
|---|---|---|
| DataForSEO Content Analysis | 100 menciones | ~$0.32 |
| Apify Instagram | 50 posts | ~$0.03 |
| Apify TikTok | 50 videos | ~$0.02 |
| Apify Twitter | 100 tweets | ~$0.04 |
| Claude API sentiment (200 items) | 20 batches | ~$0.20 |
| **Total semanal** | **~400 menciones** | **~$0.61** |

---

*Blueprint generado por MagicHack Consulting — proyecto Avianca Brand Sentiment Monitor v1.0*
