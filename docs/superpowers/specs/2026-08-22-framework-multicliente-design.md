# Framework multi-cliente — capas Mercado / Sector / Cliente

**Fecha:** 2026-08-22
**Estado:** Diseño aprobado, pendiente plan de implementación
**Primer caso nuevo:** Burger King Bolivia (restaurantes, Bolivia)

---

## 1. Contexto y diagnóstico

El repo dejó de ser el entregable de un cliente y pasó a ser el motor de brand
monitoring de MagicHack. Multi-marca ya está resuelto (Avianca y LATAM corren en
el mismo código vía `--brand`), pero el resto de la calibración sigue suelta en
el top level de `config.py` y no hay ninguna frontera entre clientes.

### Hallazgos que motivan este rediseño

| # | Hallazgo | Evidencia |
|---|---|---|
| 1 | `BRANDS` confunde dos conceptos | Avianca y LATAM están al mismo nivel, como si fueran dos clientes. No lo son: LATAM es el competidor que Avianca paga por ver. Comparten DB, share of voice y comparación en IA — cosas que jamás querríamos entre clientes reales. |
| 2 | 21 módulos importan `config` a nivel de módulo | Singleton por proceso. Impide dos clientes en la misma corrida. Ver §5. |
| 3 | La calibración de sector está mezclada con el motor | `COMPLAINT_DRIVERS`, `AVIATION_CONTEXT_*`, `BLACKLIST_DOMAIN_ROOTS`, `SHARE_OF_VOICE_*` y los prompts de IA viven en `config.py` junto a credenciales y límites. |
| 4 | No hay aislamiento por cliente | Una sola `data/avianca.db`, una sola carpeta `deploy/`, un solo `config.py`. |
| 5 | El eje geográfico no existe | `LOCATION_CODE=2170` y `RECOGNIZED_MEDIA_DOMAINS` (medios colombianos) son globales. Burger King Bolivia los rompe. |
| 6 | Las etiquetas de driver están hardcodeadas en el template | `dashboard/template.html:875` tiene `equipaje:'Equipaje', cancelacion:'Cancelaciones'…` en JS literal. |
| 7 | La fuente de reseñas está modelada como campo de marca | `brand["review_domain"]` asume Trustpilot. Un restaurante no vive en Trustpilot. |

### Hallazgos verificados contra la API real (2026-08-22)

Costo total de la verificación: **$0,31**.

| Verificación | Resultado |
|---|---|
| `location_code` de Bolivia | **2068** (país); 20083/20084/20085 (Cochabamba/La Paz/Santa Cruz); 1001500 (ciudad de Cochabamba). Disponible en `serp`, `business_data` y `keywords_data`. Costo $0. |
| Visibilidad en IA en Bolivia | **Funciona.** `burgerking.com.bo` @ 2068/es: 6 menciones, `ai_search_volume` 2.950, plataforma google. Control `avianca.com` @ 2068/es: 12 menciones, 5.600 — descarta falso positivo. |
| Fuentes citadas por la IA (`target_metrics`) | **10 dominios**: instagram.com (6), burgerking.com.bo (5), tiktok.com (3), pedidosya.com.bo (3), facebook.com (2), lpz.megacenter.com.bo (1)… |
| Ejemplos reales (`search_mentions`) | 3/3 vía `google_ai_overview`, con fuentes. Volúmenes 1.000 / 590 / 480. |
| `search_results_domain` vacío en `multi_target_metrics` | Artefacto del endpoint de comparación, **no** de Bolivia — `target_metrics` sí devuelve fuentes. |

### Dos supuestos propios que los datos desmintieron

1. **Iba a blacklistear los agregadores de delivery**, copiando el criterio de
   aerolíneas (donde Kayak/Despegar son ruido SEO). Es al revés: `pedidosya.com.bo`
   aparece como fuente **citada por la IA** sobre BK. En restaurantes el agregador
   es canal legítimo, no ruido. La blacklist del sector se define contra datos y
   probablemente sea corta.
2. **Iba a traducir los prompts de IA de aerolíneas.** Las preguntas reales sobre
   BK Bolivia son **locales**, no reputacionales: "dónde queda el más cercano",
   "cómo es el de Calacoto", "existe el de Obrajes". La intención es geográfica.
   Los prompts de categoría del sector restaurantes llevan `{city}` y el mercado
   aporta las ciudades.

---

## 2. Decisiones tomadas

| Decisión | Elección | Descartado |
|---|---|---|
| Persistencia | SQLite, un `.db` por cliente | Supabase/Postgres (el dashboard es estático y nunca consulta la base; el aislamiento por archivo es más fuerte que RLS; 866 líneas de `store/db.py` son SQLite-específicas) |
| Ejecución | Manual, en la máquina de Carlos | Nube desatendida (obligaría a Postgres); SaaS con login |
| Estructura | Un repo, `clients/<slug>/` | Repo plantilla clonado; motor como paquete pip |
| Capas | Cuatro: motor / mercado / sector / cliente | Tres (mercado y sector fundidos) |
| Jerarquía | Cliente → marca propia + competidores[] | Marcas al mismo nivel |
| Migración de Avianca | Limpia, sin compatibilidad hacia atrás | Convivencia con `--client` opcional; migrar Avianca después |
| Competidores de BK | `[]` por ahora | — |
| Drivers de restaurantes | Set semilla, recalibrado contra datos reales antes del primer reporte | Inventarlos y darlos por buenos |

---

## 3. Arquitectura

Cuatro capas. Cada una responde una pregunta distinta y cambia por razones
distintas.

```
config.py                    MOTOR    credenciales, límites, stopwords, helpers
markets/
  colombia.py                MERCADO  location_code 2170, medios colombianos, ciudades
  bolivia.py                 MERCADO  location_code 2068, medios bolivianos, ciudades
sectors/
  aerolineas.py              SECTOR   drivers, vocabulario, review_source, prompts
  restaurantes.py            SECTOR
clients/
  avianca/
    client.py                CLIENTE  market + sector + marcas + rutas
    data/avianca.db
    deploy/
  burger-king-bo/
    client.py
    data/burger-king-bo.db
    deploy/
```

**Regla de dependencia:** el motor no conoce mercados, sectores ni clientes. El
sector no conoce mercados ni clientes. El mercado no conoce nada. Solo el cliente
ata las tres. Ningún módulo del motor importa un perfil: lo recibe como parámetro
— la misma convención que ya se probó con `brand` cuando llegó multi-marca
(`config.py:52-57`).

### Aislamiento

Físico, no por convención de consulta: cada cliente tiene su archivo `.db`, su
carpeta `deploy/` y su `client.py`. Ninguna consulta puede cruzar clientes porque
ninguna conexión ve más de una base. Los competidores de un cliente viven dentro
de **su** base, porque son parte de su encargo.

Credenciales (`.env`) siguen siendo globales: son de MagicHack, no del cliente.

---

## 4. Contratos

### `markets/<slug>.py` → `MARKET`

| Campo | Tipo | Notas |
|---|---|---|
| `slug` | str | `"bolivia"` |
| `name` | str | `"Bolivia"` — se inyecta en el prompt del clasificador |
| `country_code` | str | `"BO"` |
| `language_code` | str | `"es"` |
| `location_code` | int | `2068` — verificado |
| `cities` | list[str] | `["La Paz", "Santa Cruz", "Cochabamba"]` — rellena `{city}` en los prompts de categoría |
| `recognized_media_domains` | set[str] | Medios del país que cuentan como prensa |

### `sectors/<slug>.py` → `SECTOR`

| Campo | Tipo | Notas |
|---|---|---|
| `slug`, `name` | str | |
| `complaint_drivers` | list[str] | Incluye siempre `"otro"` |
| `driver_precedence` | list[str] | Orden de desempate. Hoy vive dentro de `build_system_prompt()`; sale a datos. Se valida que sea permutación de `complaint_drivers`. |
| `driver_labels` | dict[str,str] | Reemplaza el literal JS de `template.html:875` |
| `context_words` | set[str] | Sin tildes, minúscula. Comparación por palabra completa. |
| `context_phrases` | set[str] | Multi-palabra, substring |
| `context_substring_terms` | set[str] | Seguros como substring dentro de un hashtag |
| `blacklist_domain_roots` | set[str] | |
| `review_source` | `"trustpilot"` \| `"google_business"` | |
| `ai_category_prompt_templates` | list[str] | Pueden llevar `{city}`; el mercado expande |
| `ai_brand_prompt_templates` | list[dict] | `{brand}`, `{competitor}`, `{loyalty_program}` |
| `share_of_voice_problem_terms` | list[str] | |
| `share_of_voice_commercial_terms` | list[str] | |
| `classifier_role` | str | Plantilla: `"la aerolínea {keyword} en {market_name}"` |
| `has_loyalty_program` | bool | Si es `False`, `programa_fidelidad` no está en drivers y el prompt omite la mención |

### `clients/<slug>/client.py` → `CLIENT`

| Campo | Tipo | Notas |
|---|---|---|
| `slug`, `name` | str | `slug` es el nombre de carpeta y el prefijo de archivos |
| `market` | str | slug de `markets/` |
| `sector` | str | slug de `sectors/` |
| `own_brand` | str | Debe existir en `brands` |
| `brands` | dict[str, dict] | Perfiles de marca. Forma **sin cambios** salvo lo de abajo. |
| `competitors` | list[str] | Claves de `brands` distintas de `own_brand` |
| `db_path`, `deploy_dir` | str | Relativos a la carpeta del cliente |
| `report_window_start`, `backfill_since` | str | Hoy globales en `config.py` |

**Cambios al perfil de marca:**

- Se elimina `competitors` (hoy duplicado y simétrico a mano). Se deriva: los
  competidores de una marca son las demás marcas del cliente.
- `review_domain` → `review_target`, y su forma depende de `sector["review_source"]`:
  - `trustpilot`: `str` — un dominio (`"avianca.com"`).
  - `google_business`: `list[dict]` — un elemento por sucursal,
    `{"branch": "Calacoto", "cid": "..."}`. El campo `branch` es el que puebla la
    columna homónima de `mentions` (§6).

  El cargador valida la forma contra el `review_source` del sector, así que una
  marca de restaurante con un `str` falla al cargar, no a mitad de un scraper.

**Campos requeridos vs. opcionales:** `color` es **requerido** — `build.py` deriva
de él tres variables CSS por contraste WCAG y no tiene default sensato.
`logo`, `loyalty_program`, `review_target` y `recognized_media_domains` son
opcionales: con `logo: None` el dashboard cae al wordmark tipográfico (ya
implementado), con `review_target` ausente se omite la captura de reseñas, y con
`recognized_media_domains` vacío el bloque de prensa clasifica todo como "otro".

### Cargador

`config.load_client(slug) -> RunContext`, un `@dataclass(frozen=True)` con
`client`, `market`, `sector` y helpers (`brands()`, `brand(name)`,
`competitors_of(name)`). Inmutable a propósito: ningún módulo del motor debe
poder mutar la calibración a mitad de corrida. Valida al cargar y falla con
mensaje claro — mismo criterio que el `get_brand()` actual: mejor un `ValueError`
explícito que un `KeyError` críptico dentro de un scraper.

Validaciones: sector y mercado existen; `own_brand ∈ brands`; `competitors ⊆
brands − {own_brand}`; `driver_precedence` es permutación de `complaint_drivers`;
`"otro" ∈ complaint_drivers`; si `has_loyalty_program` entonces cada marca tiene
`loyalty_program`; `review_target` tiene la forma que exige `review_source`; toda
marca tiene `color`.

---

## 5. Cambios de interfaz

Qué deja de importarse a nivel de módulo y pasa a parámetro:

| Módulo | Deja de importar | Recibe |
|---|---|---|
| `pipeline/classifier.py` | `COMPLAINT_DRIVERS` | `sector`, `market` |
| `pipeline/relevance.py` | `AVIATION_CONTEXT_*`, `BLACKLIST_DOMAIN_ROOTS` | `sector` |
| `scrapers/dataforseo_*.py` | `LOCATION_CODE`, `LANGUAGE_CODE` | `market` |
| `scrapers/dataforseo_ai_prompts.py` | prompts de `config` | `sector`, `market` |
| `scrapers/dataforseo_share_of_voice.py` | `SHARE_OF_VOICE_*` | `sector` |
| `scrapers/dataforseo_reviews.py` | — | `sector` (elige implementación) |
| `store/db.py` | `DB_PATH`, `DEFAULT_BRAND` | ruta del cliente |
| `dashboard/aggregate.py` | `REPORT_WINDOW_START`, `get_brand` | `ctx` |
| `dashboard/build.py` | `DEFAULT_BRAND`, `get_brand` | `ctx` |
| `pipeline/ai_visibility.py` | `BRANDS` | `ctx` |

Lo que **sí** sigue global en `config.py`: credenciales, actores de Apify,
límites por scraper, `SPANISH_STOPWORDS` y umbrales de idioma (recurso de idioma,
no de mercado), `WEB_CHANNEL_RETIREMENT_REASON`, `AI_VISIBILITY_MODEL`.

### CLI

`--client <slug>` es **obligatorio** en todo comando que toque datos. `--brand`
se mantiene y se valida contra las marcas de ese cliente.

```
python main.py --client avianca --brand LATAM
python main.py --client burger-king-bo --backfill
python -m dashboard.build --client burger-king-bo
```

---

## 6. Modelo de datos

### Columna nueva en `mentions`: `branch`

`TEXT NULL`. Sucursal a la que corresponde la mención. Nula para todo lo que hoy
existe y para sectores de una sola ubicación.

**Por qué columna y no `raw`:** en restaurantes la sucursal es una dimensión de
análisis, no metadato. Con 16 locales, "qué sucursal concentra las quejas" es la
pregunta de negocio; la IA ya responde por sucursal ("el de Calacoto", "el de
Obrajes"). Enterrarla en `raw` la deja fuera de todo `GROUP BY`.

Migración con el patrón existente de `store/db.py:_migrate()` — `PRAGMA
table_info` + `ALTER TABLE ADD COLUMN`, idempotente.

### Reseñas de Google Business

Scraper nuevo `scrapers/dataforseo_google_reviews.py`, familia `business_data`
(la misma de Trustpilot, ya en uso). Un listado por sucursal → `branch` poblado.
`scrapers/dataforseo_reviews.py` pasa a despachar según `sector["review_source"]`.

---

## 7. Dashboard

### Etiquetas de driver dinámicas

Marcador nuevo `__DRIVER_LABELS__` inyectado como JSON, reemplazando el literal
de `template.html:875`. Mismo mecanismo que los 9 marcadores existentes.

### Bloques que requieren ≥2 marcas

Con `competitors: []`, **share of voice** y **comparación en IA** no tienen
contenido posible. Regla: `build.py` omite esas claves del payload, y el template
oculta la sección cuando su clave falta. No se muestra un bloque vacío ni un
gráfico de una sola barra — un cliente sin competidores contratados no debe ver
el hueco de algo que no compró.

Los bloques de visibilidad en IA de **marca propia** (menciones, volumen, fuentes
citadas, ejemplos de respuesta) sí funcionan con una sola marca — verificado
contra BK Bolivia — y se mantienen.

---

## 8. Sector `restaurantes` — contenido inicial

**Drivers semilla** (andamiaje declarado, no entregable):
`pedido_incorrecto`, `demora`, `atencion_cliente`, `calidad_comida`, `limpieza`,
`precios`, `delivery`, `app_canales`, `otro`.

Sin `programa_fidelidad` (`has_loyalty_program: False`).

**Recalibración obligatoria antes del primer reporte:** mismo procedimiento que
descubrió los drivers de Avianca — pasar las quejas de `"otro"` por el
clasificador en lotes con codebook evolutivo, sin categorías predefinidas, y
crear driver solo donde haya volumen propio. En Avianca ese proceso desmintió una
hipótesis ("denegación de embarque" no existía) y descubrió tres categorías que
nadie había anticipado. No se da por buena la lista semilla.

**`ai_category_prompt_templates`** con `{city}`: "¿dónde comer hamburguesas en
{city}?", "¿cuál es la mejor hamburguesería de {city}?".

**`blacklist_domain_roots`**: arranca **vacía**. Los agregadores de delivery no
son ruido en este sector. Se llena contra datos reales de la primera corrida.

**`context_words`**: vocabulario de comida rápida y servicio en restaurante
(hamburguesa, pedido, delivery, local, sucursal, mesa, combo…), a validar contra
la primera captura igual que se hizo con el vocabulario aeronáutico.

---

## 9. Mercado `bolivia` y cliente `burger-king-bo`

```
MARKET  slug=bolivia · country=BO · language=es · location_code=2068
        cities=[La Paz, Santa Cruz, Cochabamba]
        recognized_media_domains: por definir (medios bolivianos)

CLIENT  slug=burger-king-bo · name="Burger King Bolivia"
        market=bolivia · sector=restaurantes
        own_brand="Burger King" · competitors=[]
        brands["Burger King"]:
          keyword                  "Burger King"
          instagram_profiles       ["https://www.instagram.com/burgerking.bolivia/"]
          tiktok_hashtags          ["burgerkingbolivia", "burgerkingbo"]   (a validar)
          tiktok_official_accounts {"burgerkingbolivia"}
          domains                  {burgerking.com.bo, pide.burgerking.com.bo,
                                    cmsappbk.burgerking.com.bo}
          review_target            por definir (listados de Google Business por sucursal)
          loyalty_program          None
          color / logo             por definir
```

Franquiciado: Bolivian Foods S.A., ~16 restaurantes desde 1999.

**Pendiente de calibración con el cliente:** lista exacta de sucursales, color de
marca y logo, hashtags reales de TikTok, medios bolivianos reconocidos.

---

## 10. Migración de Avianca

Limpia, sin compatibilidad hacia atrás. Un solo camino en el código.

1. Respaldo de `data/avianca.db` (patrón ya usado, 9 backups en `data/backups/`).
2. `data/avianca.db` → `clients/avianca/data/avianca.db`; `deploy/` → `clients/avianca/deploy/`.
3. `config.BRANDS` → `clients/avianca/client.py` (Avianca + LATAM, `own_brand="Avianca"`, `competitors=["LATAM"]`).
4. Calibración aeronáutica de `config.py` → `sectors/aerolineas.py`; `LOCATION_CODE`/medios → `markets/colombia.py`.
5. `--client` obligatorio.
6. `.env`: se eliminan `BRAND_KEYWORD`, `COUNTRY_CODE`, `LANGUAGE_CODE`, `LOCATION_CODE` (pasan al cliente/mercado).

**Criterio de éxito:** el dashboard de Avianca regenerado tras la migración es
idéntico a `dashboard/avianca_dashboard_2026-08-22.html`, salvo la fecha de
generación. Si difiere en cualquier otra cosa, la migración cambió algo que no
debía.

Este criterio se verifica **dos veces**: al cerrar la fase 3 (aislamiento) y otra
vez al cerrar la fase 6 (dashboard). La fase 6 toca `template.html` para hacer
dinámicas las etiquetas de driver, y esa es exactamente la clase de cambio que
puede alterar la salida sin que nadie lo note — las etiquetas de aerolíneas deben
salir idénticas cuando vienen del sector en vez del literal JS.

---

## 11. Testing

31 archivos de test; 16 importan `config`. Estrategia:

- **Fixtures sintéticos** en `tests/conftest.py`: un mercado, un sector y un
  cliente de prueba que no sean ni Avianca ni BK. Los tests del motor dejan de
  depender de datos de un cliente real.
- **Tests de calibración**: los que hoy verifican comportamiento con datos de
  Avianca (`test_relevance.py`, `test_classifier.py`) se reapuntan al sector
  `aerolineas` explícitamente.
- **Test de contrato por capa**: cargar cada mercado, sector y cliente del repo y
  validar su forma. Un `sectors/*.py` mal escrito falla en la suite, no en una
  corrida que gasta API.
- **Test de aislamiento**: cargar dos clientes en el mismo proceso y verificar que
  sus rutas de DB difieren y que ninguna consulta ve marcas del otro.
- **Test de regresión de migración**: el criterio de éxito de §10, automatizado.

---

## 12. Riesgos y límites declarados

1. **Los drivers de restaurantes son semilla, no verdad.** Se recalibran contra
   datos reales antes del primer reporte. Riesgo asumido conscientemente.
2. **El scraper de Google Business es código nuevo** contra una parte de
   `business_data` que el repo todavía no usa (solo Trustpilot). Es el trabajo
   menos predecible del plan.
3. **Volumen de BK Bolivia sin medir.** 6 menciones en IA y 2.950 de volumen es
   señal real pero menor que Avianca (12 / 5.600 en el mismo país). Instagram y
   TikTok pueden traer volúmenes bajos; si el mes sale flaco, el dashboard lo
   mostrará en vez de promediarlo, igual que hoy.
4. **Facebook queda fuera.** BK Bolivia tiene canal activo y la IA lo cita como
   fuente, pero el motor no cubre Facebook y agregarlo no es parte de esto.
5. **`recognized_media_domains` de Bolivia está sin definir.** Hasta llenarlo, el
   bloque de prensa de BK subclasifica medios como "otro".
6. **Un cliente nuevo del mismo mercado y sector no está probado.** El diseño lo
   soporta; el primer caso real lo dirá.

### No-objetivos

Postgres/Supabase · ejecución en la nube · login de clientes · multi-idioma ·
Facebook · aislamiento criptográfico entre clientes · empaquetar el motor como
librería instalable.

---

## 13. Fases de implementación

| # | Fase | Entregable verificable |
|---|---|---|
| 1 | Capas y cargador | `markets/`, `sectors/`, `clients/` + `load_client()` + tests de contrato. Avianca sigue corriendo igual. |
| 2 | Desacoplar módulos | Ningún módulo del motor importa calibración. Suite verde. |
| 3 | Aislamiento y CLI | DB y deploy de Avianca movidos, `--client` obligatorio, test de regresión de §10 en verde. |
| 4 | Bolivia + restaurantes + BK | Los tres perfiles cargan y validan. Sin gastar API. |
| 5 | Reseñas Google Business + `branch` | Scraper nuevo, columna migrada, reseñas reales de una sucursal. |
| 6 | Dashboard | `__DRIVER_LABELS__` dinámico, bloques sin competidores ocultos. |
| 7 | Primera captura BK + recalibración | Corrida real, drivers recalibrados contra datos, primer dashboard. |

Las fases 1-3 no cambian ningún comportamiento observable: son refactor con red
de tests. La 4 es configuración. El riesgo real está en 5 y 7.

### Descomposición en dos planes

Este spec cubre dos proyectos con criterios de éxito distintos, y conviene
implementarlos como dos planes separados:

- **Plan A — Extracción del framework (fases 1-4).** Éxito = Avianca corre igual
  que hoy sobre la estructura nueva, y los perfiles de Bolivia/restaurantes/BK
  cargan y validan. No gasta un centavo de API. Todo el riesgo es de refactor y
  está cubierto por la suite de tests más el criterio de §10.
- **Plan B — Onboarding de Burger King Bolivia (fases 5-7).** Éxito = primer
  dashboard de BK con drivers recalibrados contra datos reales. Depende de Plan A
  terminado, gasta API, e incluye el único código genuinamente nuevo (scraper de
  Google Business) y el único trabajo de calibración con datos en la mano.

Mezclarlos haría que un problema de scraping bloquee un refactor que ya funciona,
o al revés. Plan A tiene que poder darse por cerrado sin BK.
