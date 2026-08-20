# Avianca Sentiment Monitor v2 — Backfill 4 meses + Dashboard HTML

**Fecha:** 2026-08-19
**Estado:** Diseño aprobado, pendiente plan de implementación

---

## 1. Contexto y diagnóstico

El pipeline v1 (`main.py` → scrapers → normalizer → sentiment_engine → supabase/excel)
está estructuralmente bien pero no persiste nada y su cobertura real es
sustancialmente peor de lo que aparenta.

### Hallazgos que motivan este rediseño

| # | Hallazgo | Evidencia |
|---|---|---|
| 1 | No hay persistencia | `.env` sin `SUPABASE_URL`/`SUPABASE_KEY`; `supabase_writer` retorna 0. No existe proyecto Supabase de Avianca en la cuenta. Toda la data vive en un Excel de 383 filas. |
| 2 | Fechas web falsas | Las 100 filas `platform=web` tienen `published_at == fetched_at == 2026-06-05`. DataForSEO no devolvió `date_published` y el código cae a un fallback silencioso. |
| 3 | Twitter no produjo nada | 0 filas de `platform=twitter` en el dataset. |
| 4 | 26% del dataset sin analizar | Las 100 menciones web salieron `pos=0.0 neg=0.0 neu=1.0`. `sentiment_engine` excluye `platform == "web"` asumiendo sentiment nativo de DataForSEO, que vino vacío. |
| 5 | Capa web es ruido SEO | 63 de 100 filas son el agregador `rehlat.*` replicado en 12 dominios de país. También `tidal.com` (una playlist) y `jetcost.pl` (en polaco). Único filtro existente: excluir dominios oficiales de Avianca. |
| 6 | Instagram mide el canal propio | Solo extrae comentarios de posts de `@avianca` / `@aviancacolombia`. No es listening de la conversación. |
| 7 | Dos definiciones de "queja" | Web usa heurística `neg > 0.4 and neg > pos`; social usa criterio del LLM. No comparables. |
| 8 | Clasificador frágil | Sin reintentos. Un batch fallido deja 10 menciones neutras en silencio. `zip(batch, sentiments)` trunca sin avisar si el LLM devuelve menos objetos. |
| 9 | Dashboard nunca renderizó | `SUPABASE_URL=''` y `SUPABASE_KEY=''` hardcodeados vacíos en `dashboard/index.html`. |
| 10 | `on_conflict` sin constraint | El upsert declara `platform,source_url` pero no existe SQL de creación de tabla ni unique constraint en el repo. |

### Señal aprovechable del dataset actual

- 38% de comentarios en Instagram son quejas reales (72/189); 19% en TikTok (18/94).
- Emociones: `anger 74 · happiness 80 · love 37 · sadness 25 · neutral 167`.
- 398.364 de engagement acumulado (315.726 likes, 67.406 shares, 15.232 comentarios) — nunca usado.
- 239 autores únicos.
- TikTok ya trae histórico de 4 meses (2026-01-27 → 2026-06-05).

---

## 2. Decisiones tomadas

| Decisión | Elección | Descartado |
|---|---|---|
| Persistencia | SQLite local + HTML autocontenido | Supabase live; ambos |
| Value-add | Solo categorización de quejas por driver operativo | Ponderación por engagement; benchmark LATAM; detección de picos y rutas |
| Fuentes del backfill | DataForSEO (con filtro) + TikTok + Instagram ampliado | Twitter/X con actor de pago; búsqueda por menciones de terceros |
| Motor LLM | DeepSeek (el que ya funciona) | Claude Haiku (requiere `ANTHROPIC_API_KEY` nueva) |

**Rango del backfill:** 2026-04-19 → 2026-08-19 (120 días).

**Nota sobre value-adds descartados:** ponderación por engagement, benchmark vs
LATAM y detección de picos/rutas quedaron fuera por YAGNI explícito del usuario.
El schema no debe cerrarles la puerta (los campos de engagement ya se persisten),
pero no se implementa lógica para ellos.

---

## 3. Arquitectura

```
scrapers/*  ──►  normalizer  ──►  relevance  ──►  classifier  ──►  store/db (SQLite)
                                                                        │
                                                     store/seed_excel ──┤
                                                                        ▼
                                                             dashboard/build.py
                                                                        │
                                                                        ▼
                                              dashboard/avianca_dashboard_<fecha>.html
```

Cada unidad tiene una responsabilidad y una interfaz clara:

- **scrapers/**: dado un `since: date`, devuelven `list[dict]` en el schema unificado. No clasifican, no filtran por relevancia.
- **normalizer**: valida tipos, limpia texto, asigna `date_confidence`. No descarta por contenido.
- **relevance**: decide si una mención es sobre Avianca-la-aerolínea o es ruido. Pura, testeable, sin red.
- **classifier**: sentiment + emoción + `is_complaint` + `complaint_driver` en un solo llamado LLM. Único punto que habla con DeepSeek.
- **store/db**: única capa que toca SQLite. Upsert idempotente por fingerprint.
- **dashboard/build**: lee la DB, agrega, inyecta JSON en la plantilla, escribe el HTML. No consulta APIs.

---

## 4. Modelo de datos

`data/avianca.db`

### Tabla `mentions`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | TEXT PK | uuid4 |
| `fingerprint` | TEXT UNIQUE NOT NULL | `sha256(platform + '\|' + source_url + '\|' + author + '\|' + text)` — texto completo |
| `platform` | TEXT NOT NULL | `web` / `instagram` / `tiktok` |
| `source_url` | TEXT | |
| `text` | TEXT NOT NULL | |
| `author` | TEXT | |
| `published_at` | TEXT | ISO 8601, NULL si no hay fecha |
| `date_confidence` | TEXT NOT NULL | `exact` / `approx` / `unknown` |
| `country` | TEXT | |
| `likes` | INTEGER DEFAULT 0 | |
| `shares` | INTEGER DEFAULT 0 | |
| `comments_count` | INTEGER DEFAULT 0 | |
| `sentiment_positive` | REAL | |
| `sentiment_negative` | REAL | |
| `sentiment_neutral` | REAL | |
| `emotion` | TEXT | `happiness` / `anger` / `love` / `sadness` / `neutral` |
| `is_complaint` | INTEGER | 0/1 |
| `complaint_driver` | TEXT | ver §6; NULL si `is_complaint = 0` |
| `classification_status` | TEXT NOT NULL | `classified` / `unclassified` |
| `raw` | TEXT | JSON serializado |
| `fetched_at` | TEXT | ISO 8601 |
| `run_id` | TEXT | FK → `runs.id` |

Índices: `published_at`, `platform`, `is_complaint`, `complaint_driver`.

**Semántica del `fingerprint`:** se calcula **después** de normalizar (sobre el
texto ya limpiado y recortado), nunca sobre el texto crudo. De lo contrario un
espacio en blanco distinto generaría un duplicado.

Se hashea el **texto completo**, no un prefijo. Un diseño anterior truncaba a 80
caracteres; se descartó porque las quejas de aerolínea tienen aperturas de
plantilla ("Avianca canceló mi vuelo y no me han dado respuesta desde hace…") y
dos comentarios distintos en la misma URL podían colisionar y perderse en
silencio. La asimetría decide: un duplicado falso es una fila de más, visible y
auditable; una fusión falsa es pérdida de datos irrecuperable.

El `author` entra en el hash por una razón medida en datos reales: en el v1, el
`source_url` de **todos** los comentarios de Instagram resolvía a la misma URL
(`apify_instagram.py` cae a `post_urls[0]` cuando el ítem no trae `url` propia).
Con `source_url` constante, dos personas distintas que escriban el mismo texto
producían el mismo fingerprint y una se perdía sin rastro — caso confirmado en el
Excel v1: `catherine_zik_oppenheimer` y `valentina_ahumada977` fusionadas.
Incluir el autor discrimina personas distintas; un mismo autor repitiendo texto
idéntico sí se deduplica, que es el comportamiento deseado ante re-scrapes.

**Pendiente asociado:** `scrapers/apify_instagram.py` debe construir una URL
distinta por comentario en vez de caer a `post_urls[0]`. El fingerprint con autor
mitiga el síntoma; la URL degenerada es la causa.

**Semántica del `run_id`:** guarda la corrida que **insertó** la mención por
primera vez. Un upsert que encuentra el fingerprint existente no lo sobrescribe
— así se preserva cuándo se vio por primera vez cada mención.

### Tabla `runs`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | TEXT PK | uuid4 |
| `started_at` / `finished_at` | TEXT | ISO 8601 |
| `mode` | TEXT | `weekly` / `backfill` / `seed` |
| `since` | TEXT | fecha de inicio solicitada, NULL en `weekly` |
| `raw_count` | INTEGER | menciones traídas por scrapers |
| `filtered_count` | INTEGER | descartadas por relevance |
| `inserted_count` | INTEGER | nuevas |
| `duplicate_count` | INTEGER | ya existían |
| `notes` | TEXT | errores por fuente |

### `date_confidence` — reglas

- `exact`: la fuente entregó fecha de publicación real (TikTok `createTimeISO`, Instagram `timestamp`, DataForSEO `date_published` no nulo).
- `approx`: fecha derivada del contenedor (ej. comentario de Instagram sin timestamp propio → fecha del post).
- `unknown`: no hay fecha. **`published_at` queda NULL, no se rellena con `fetched_at`.**

Las menciones `unknown` **se excluyen de todo gráfico temporal** y se reportan
en el bloque de calidad de datos del dashboard. Este campo existe específicamente
para que el timeline de 4 meses no mienta (hallazgo #2).

---

## 5. Filtro de relevancia (`pipeline/relevance.py`)

Función pura `is_relevant(mention: dict) -> tuple[bool, str]` que devuelve
`(pasa, razón_de_descarte)`. Aplica solo a `platform == "web"`; el contenido
social pasa directo (ya viene de perfiles/hashtags de la marca).

Reglas, en orden:

1. **Dominio oficial de la marca** → descartar (comportamiento actual, se conserva).
2. **Blacklist de agregadores/OTAs** → descartar. Lista base configurable en `config.py`:
   `rehlat`, `jetcost`, `kayak`, `despegar`, `kiwi.com`, `skyscanner`, `expedia`,
   `trip.com`, `edreams`, `viajala`, `momondo`, `cheapflights`, `tidal`,
   `atoallinks`. Match por **raíz de dominio**, de modo que `rehlat.es`,
   `au.rehlat.com` y `www.rehlat.mx` caen todos con una sola entrada.
3. **Idioma** → conservar solo español. Detección heurística sin dependencia nueva:
   presencia de stopwords españolas (`que, para, con, los, las, del, una, por, como,
   pero, más, este, esta, sus, muy`) en el texto.
   **Umbral inicial:** textos de ≥15 palabras requieren ≥2 stopwords distintas;
   textos de <15 palabras **no se filtran por idioma** (muy corto para decidir, la
   regla 4 los cubre). El umbral se valida contra las 383 filas existentes durante
   la implementación y se ajusta si produce falsos negativos.
4. **Keyword presente** → el texto debe contener `avianca` (case-insensitive).
   Descarta páginas que solo mencionan la marca en metadatos.

Toda mención descartada se cuenta en `runs.filtered_count` y su razón se agrega
al bloque de calidad de datos. No se persiste el descarte.

**Efecto esperado:** las 100 menciones web actuales se reducen drásticamente
(las 63 de `rehlat` caen por regla 2, `jetcost.pl` por 2 y 3, `tidal` por 2).
Esto es correcto: el conteo baja antes de subir.

---

## 6. Clasificador (`pipeline/classifier.py`)

Reemplaza `pipeline/sentiment_engine.py`. Un solo llamado a DeepSeek por batch
devuelve sentiment, emoción, si es queja y el driver — sin costo adicional
respecto al v1.

### Contrato de salida por mención

```json
{
  "sentiment_positive": 0.0,
  "sentiment_negative": 0.0,
  "sentiment_neutral": 1.0,
  "emotion": "happiness",
  "is_complaint": false,
  "complaint_driver": null
}
```

### Drivers válidos

`equipaje` · `cancelacion` · `demora` · `atencion_cliente` · `cobros_tarifas` ·
`lifemiles` · `asientos_comida` · `reembolsos` · `otro`

`complaint_driver` es `null` cuando `is_complaint` es `false`. Si `is_complaint`
es `true` el driver es obligatorio; ante duda el modelo debe usar `otro`.

**Orden de precedencia (desempate obligatorio).** Muchas quejas encajan en dos
drivers a la vez: una maleta perdida por un vuelo cancelado, un cobro que además
no fue reembolsado. Sin una regla, el mismo tipo de queja se reparte de forma no
determinista y el reporte agregado deja de significar algo. El modelo elige el
**primero que aplique** en este orden:

`cancelacion` → `demora` → `equipaje` → `reembolsos` → `cobros_tarifas` →
`lifemiles` → `asientos_comida` → `atencion_cliente` → `otro`

Dos consecuencias deliberadas del orden:

- Las disrupciones de vuelo (cancelación, demora) ganan porque son la causa raíz
  accionable: si la maleta no llegó porque cancelaron el vuelo, el problema a
  arreglar es la cancelación.
- `atencion_cliente` va casi al final **a propósito**. Casi toda queja incluye
  "y nadie me ayudó"; si compitiera de igual a igual se tragaría el resto de
  categorías y el driver dejaría de informar. Solo gana cuando el mal servicio
  **es** la queja, no su acompañamiento.

Además, los cobros de equipaje pertenecen a `cobros_tarifas`, no a `equipaje`:
`equipaje` cubre el manejo físico (maletas perdidas, dañadas, demoradas).

### Robustez (corrige hallazgos #4 y #8)

- **Todas las plataformas pasan por el clasificador**, incluida `web`. Se elimina
  la exclusión `platform == "web"`.
- **Una sola definición de queja:** la del LLM. Se elimina la heurística
  `neg > 0.4 and neg > pos` de `dataforseo_scraper.py`.
- **Validación de longitud:** si el array devuelto no tiene el mismo largo que el
  batch, no se hace `zip`. Se reintenta el batch completo una vez; si vuelve a
  fallar, se procesa item por item.
- **Reintentos:** 1 reintento con backoff exponencial ante error de red o JSON
  inválido (dos intentos en total por lote). No más: ante un desajuste de longitud,
  repetir el mismo lote rara vez ayuda — el mecanismo real de recuperación es la
  caída a item por item. Reintentos extra de lote solo queman dinero en la ruta de
  fallo: con un lote de 10 que falla de forma persistente, 1 reintento cuesta 22
  llamados y 2 reintentos cuestan 33.
- **Fallo explícito:** lo que no se logre clasificar se guarda con
  `classification_status = 'unclassified'`, no como neutral silencioso. El
  dashboard los excluye de los promedios de sentiment y los reporta en calidad de datos.
- **Normalización de driver:** si el modelo devuelve un driver fuera de la lista,
  se mapea a `otro`.

---

## 7. Ingesta y backfill

### CLI (`main.py`)

```
python main.py                                   # corrida normal (últimos 7 días)
python main.py --backfill --since 2026-04-19     # backfill histórico
python main.py --seed-excel <archivo.xlsx>       # importa Excel existente
python main.py --schedule                        # semanal, lunes 8am
```

### Parámetro `since` por fuente

| Fuente | Mecanismo | Cobertura 4 meses |
|---|---|---|
| DataForSEO | `date_from` en el payload (ya soportado) | Completa |
| TikTok | `oldestPostDate` del actor `clockworks/tiktok-scraper` | Completa |
| Instagram | Subir `resultsLimit` de posts de 20 a 80; filtrar comentarios por fecha del post | Parcial — limitada por cuántos posts publicó la marca |

Twitter/X queda fuera de v2. `scrapers/apify_twitter.py` se conserva en el repo
pero se retira del arreglo de scrapers activos en `main.py`, con un comentario
que explica por qué (actor de búsqueda histórica es de pago).

### Semilla desde Excel (`store/seed_excel.py`)

Importa `avianca_mentions_2026-06-05.xlsx` para rescatar el histórico de TikTok
de enero–junio ya pagado. Mapea columnas en español a campos del schema, asigna
`date_confidence`:

- Filas `web` con `published_at == fetched_at` → `unknown` (fecha falsa conocida).
- Resto → `exact`.

**Todas las filas importadas entran con `classification_status = 'unclassified'`
y se reclasifican.** No se conserva la clasificación del v1, por dos razones:

1. Las filas `web` nunca fueron analizadas (hallazgo #4).
2. Las filas sociales tienen `is_complaint` pero **no tienen `complaint_driver`**
   — el campo no existía en v1. Reclasificar es la única forma de que el dataset
   quede homogéneo bajo una sola definición de queja (hallazgo #7) y con driver
   asignado en todas las quejas.

Costo de reclasificar 383 filas: ~39 batches, despreciable.

El seed pasa por el mismo filtro de relevancia y el mismo dedup por fingerprint,
de modo que correrlo dos veces es idempotente.

---

## 8. Dashboard

`python dashboard/build.py` → `dashboard/avianca_dashboard_<YYYY-MM-DD>.html`

Un archivo autocontenido: Chart.js vendorizado inline, data inyectada como JSON.
Funciona offline, con doble clic, y se puede enviar por correo.

**Lenguaje visual:** se conserva el de `dashboard/index.html` — navy `#0D1117`,
naranja `#F97316`, JetBrains Mono + Inter. Se corrige el `overflow: hidden` del
`body` que impide hacer scroll.

### Bloques

| # | Bloque | Contenido |
|---|---|---|
| 1 | KPIs | Total menciones · % quejas · Net Sentiment (pos−neg) · rango real de fechas · nº fuentes |
| 2 | Timeline 4 meses | Volumen por plataforma (área apilada) + línea de sentiment neto. **Solo menciones con `date_confidence != 'unknown'`** |
| 3 | Drivers de queja | Barras horizontales por driver, con % del total de quejas y tendencia mes a mes |
| 4 | Driver × plataforma | Heatmap: dónde se queja cada audiencia de qué |
| 5 | Sentiment y emociones | Distribución agregada (dona + barras) |
| 6 | Tabla explorable | Todas las menciones. Filtros por plataforma, driver, sentimiento y rango de fechas; búsqueda de texto libre; link al post original |
| 7 | Top quejas por engagement | Ordenadas por `likes + shares + comments_count` |
| 8 | Calidad de datos | Menciones sin fecha · descartadas por relevancia **en la última corrida** · `unclassified` · cobertura por fuente y por mes |

El bloque 8 es deliberado y no negociable: el reporte debe declarar los límites
de su propia cobertura.

**Las descartadas por ruido se reportan por corrida, no como acumulado.** El
pipeline no persiste las menciones que descarta, de modo que no hay forma de
deduplicarlas entre corridas: volver a correr el seed sobre el mismo Excel vuelve
a contar las mismas 96, y sumarlas daría 192. Un acumulado histórico veraz es
imposible sin guardar los descartes, y guardarlos no vale la pena. Se reporta
entonces el número de la última corrida, etiquetado como tal — coherente con el
resto del proyecto: no se publica una cifra que no se pueda sostener.

**Nota de implementación:** cargar el skill `dataviz` antes de escribir código de
gráficos, y el skill `frontend-design` para la maquetación.

---

## 9. Plan de archivos

```
+ store/__init__.py
+ store/db.py                    SQLite: schema, migraciones, upsert, queries de agregación
+ store/seed_excel.py            importa el Excel existente
+ pipeline/classifier.py         sentiment + emoción + queja + driver, con reintentos
+ pipeline/relevance.py          filtro anti-ruido (puro)
+ dashboard/build.py             SQLite → HTML autocontenido
+ dashboard/template.html        plantilla (evoluciona index.html)
+ dashboard/vendor/chart.umd.min.js
+ data/                          contiene avianca.db
+ tests/                         ver §10

~ main.py                        --backfill --since / --seed-excel; retira twitter
~ config.py                      DRIVERS, BLACKLIST_DOMAINS, rangos; elimina SUPABASE_*
~ pipeline/normalizer.py         asigna date_confidence; deja de rellenar fechas
~ scrapers/dataforseo_scraper.py parámetro since; elimina heurística is_complaint
~ scrapers/apify_tiktok.py       parámetro since vía oldestPostDate
~ scrapers/apify_instagram.py    parámetro since; posts 20 → 80
~ requirements.txt               elimina supabase, gspread, google-auth
~ .env.example                   elimina SUPABASE_*; corrige ANTHROPIC → DEEPSEEK

- pipeline/supabase_writer.py    borrado
- pipeline/sentiment_engine.py   reemplazado por classifier.py
```

`pipeline/excel_writer.py` se conserva sin cambios: sigue siendo útil como
export tabular y no estorba.

---

## 10. Testing

TDD sobre las unidades con lógica real. Los scrapers se prueban con fixtures de
respuesta grabadas; **ningún test golpea una API**.

| Módulo | Casos |
|---|---|
| `relevance` | dominio oficial descartado; `rehlat.es` / `au.rehlat.com` / `www.rehlat.mx` caen con una entrada de blacklist; texto en polaco descartado; texto en español sin la palabra "avianca" descartado; mención legítima pasa |
| `store/db` | fingerprint idéntico no duplica; re-correr el mismo lote es idempotente; texto distinto con misma URL sí inserta |
| `classifier` | parseo de respuesta con fences de código; longitud desigual dispara reintento y luego item-por-item; driver inválido → `otro`; fallo total marca `unclassified` y no neutral |
| `normalizer` | `date_confidence` correcto para cada fuente; fecha ausente deja `published_at` NULL |
| `seed_excel` | filas web del Excel entran como `unknown` + `unclassified`; correrlo dos veces no duplica |
| `dashboard/build` | agregaciones excluyen `unknown` del timeline y `unclassified` de promedios de sentiment; HTML generado contiene el JSON esperado |

---

## 11. Costos

| Concepto | Estimado |
|---|---|
| Backfill 4 meses (DataForSEO + TikTok + Instagram + clasificación LLM) | ~$3–5 USD, una vez |
| Corrida semanal posterior | < $1 USD |

Cifras a confirmar contra las cuentas reales de DataForSEO y Apify durante la
implementación.

---

## 12. Riesgos y límites declarados

1. **El conteo de menciones bajará antes de subir.** Las 100 filas web actuales
   se reducen drásticamente al aplicar relevancia. Es el resultado correcto.
2. **Sin Twitter/X la cobertura queda en 3 fuentes.** X es donde más se queja la
   gente de aerolíneas en Colombia. Decisión consciente del usuario; el gap debe
   declararse en el bloque 8 del dashboard.
3. **Instagram sigue midiendo el canal propio.** Ampliar a 80 posts da más
   profundidad histórica pero no convierte esto en listening de la conversación
   completa. Sigue siendo "qué comentan en el muro de Avianca".
4. **La cobertura por mes será desigual.** TikTok tiene histórico real; Instagram
   depende de la frecuencia de publicación de la marca; DataForSEO depende de qué
   tanto indexó. El dashboard debe mostrar esto, no promediarlo.
5. **Detección de idioma heurística** puede tener falsos negativos con textos muy
   cortos. Mitigado con la excepción de <15 palabras; umbral a validar contra las
   383 filas existentes.

---

## 13. Fases de implementación

El plan de implementación debe ordenarse así — cada fase deja algo verificable
sin depender de la siguiente:

| Fase | Entregable | Verificable con |
|---|---|---|
| 1 | `store/db.py` + `pipeline/relevance.py` + `store/seed_excel.py` | Las 383 filas del Excel entran a SQLite, el ruido de `rehlat` queda fuera, correr el seed dos veces no duplica |
| 2 | `pipeline/classifier.py` + `pipeline/normalizer.py` modificado | Las filas seed quedan clasificadas con driver; los fallos aparecen como `unclassified`, no como neutral |
| 3 | Scrapers con `since` + `main.py --backfill` | Backfill real de 4 meses corriendo contra las APIs |
| 4 | `dashboard/build.py` + `template.html` | HTML autocontenido que abre con doble clic y muestra los 8 bloques |

La fase 3 es la única que gasta dinero. Las fases 1, 2 y 4 se pueden desarrollar
y probar completas contra los datos del Excel semilla, sin tocar ninguna API.
