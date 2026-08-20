# Avianca Sentiment Monitor v2

Pipeline que recolecta menciones de Avianca en Instagram, TikTok y web (vía
DataForSEO y Apify), las filtra por relevancia, las clasifica por sentiment y
driver de queja con un LLM, y las acumula en una base SQLite local. El
resultado se explora con un dashboard HTML autocontenido, sin backend ni
conexión a internet.

## Requisitos

- Python 3.12
- Instalar dependencias:

  ```bash
  pip install -r requirements.txt
  ```

- Variables de entorno en `.env` (ver `.env.example`):

  | Variable | Para qué |
  |---|---|
  | `DATAFORSEO_LOGIN` | Autenticación en la API de DataForSEO (menciones web) |
  | `DATAFORSEO_PASSWORD` | Autenticación en la API de DataForSEO |
  | `APIFY_API_TOKEN` | Actores de Apify para Instagram y TikTok |
  | `DEEPSEEK_API_KEY` | Motor de clasificación (sentiment + driver de queja) |

  `BRAND_KEYWORD`, `COUNTRY_CODE`, `LANGUAGE_CODE` y `LOCATION_CODE` también
  se leen de `.env` pero tienen defaults razonables para Colombia/Avianca en
  `config.py`.

## Nota para Windows

La consola de Windows (cp1252) no imprime tildes ni eñes por defecto y el
proceso puede reventar al intentar imprimirlas. Antepone
`PYTHONIOENCODING=utf-8` a cualquier comando de este proyecto que vaya a
imprimir texto con acentos (prácticamente todos):

```bash
PYTHONIOENCODING=utf-8 python main.py --backfill --since 2026-04-19
```

## Comandos de la CLI

Todos se invocan como `python main.py <flag>`:

| Comando | Qué hace |
|---|---|
| `--backfill` | Corrida histórica desde `config.BACKFILL_SINCE` (por defecto) contra las tres fuentes en vivo: DataForSEO, Instagram y TikTok. Gasta dinero real de scraping. |
| `--since YYYY-MM-DD` | Fecha de inicio explícita para la corrida (se combina con `--backfill` o se usa sola para una corrida semanal). Si se pasa, siempre gana sobre el cálculo automático. |
| `--seed-excel <archivo.xlsx>` | Importa un Excel del pipeline v1 (Supabase) a la base SQLite v2. Idempotente: correrlo dos veces no duplica filas. |
| `--classify` | Reclasifica solo las menciones pendientes (`unclassified`) que quedaron en la base, sin volver a scrapear. Útil para reintentar fallos de la API del clasificador. |
| `--export-excel` | Vuelca la base SQLite completa a un `.xlsx`. |
| `--schedule` | Deja el proceso corriendo y ejecuta el pipeline automáticamente cada lunes a las 8am. |

Sin flags, `python main.py` corre una corrida semanal (`weekly`). Esta
corrida **sí está acotada por fecha** aunque no se pase `--since`: calcula
un `since` incremental como la fecha de inicio de la última corrida
terminada menos un día de margen (o 7 días atrás si no hay corrida previa
registrada). Sin esto, DataForSEO repetiría siempre la misma ventana desde
`config.BACKFILL_SINCE` y el filtro de fecha de Instagram quedaría
deshabilitado, así que cada corrida "semanal" se comportaría como un
mini-backfill que paga el costo completo de Apify cada vez.

## Dashboard

Genera el HTML autocontenido con los datos acumulados en la base:

```bash
PYTHONIOENCODING=utf-8 python -m dashboard.build
```

Esto escribe `dashboard/avianca_dashboard_<fecha>.html`. Chart.js va inline
(vendorizado en `dashboard/vendor/`) y los datos se inyectan como JSON en el
propio archivo, así que el HTML abre con doble clic y funciona sin conexión
(las tipografías de Google Fonts son la única referencia externa; si no hay
red, el navegador cae a una fuente del sistema y el resto del dashboard —
gráficos y datos incluidos — funciona igual).

## Limitaciones declaradas

1. **Sin Twitter/X.** El actor de Apify con búsqueda histórica por rango de
   fechas en X es de pago; v2 no lo incluye. `scrapers/apify_twitter.py`
   se conserva pero no está en la lista de scrapers activos.
2. **Instagram mide solo el canal propio.** Los comentarios vienen de los
   posts de las cuentas oficiales de Avianca, no de la conversación general
   de la plataforma. Es "qué comentan en el muro de Avianca", no listening
   completo de Instagram.
3. **La cobertura por mes es desigual.** TikTok tiene histórico real,
   Instagram depende de la frecuencia de publicación de la marca, y
   DataForSEO depende de qué tanto indexó Google. El dashboard muestra esta
   variación mes a mes en vez de promediarla.
4. **Las menciones sin fecha se excluyen del timeline.** Cuando una fuente
   no trae fecha de publicación, `published_at` queda `NULL` y
   `date_confidence = 'unknown'` en vez de inventarse con la fecha de
   scraping. Esas menciones no aparecen en los gráficos temporales ni en
   los promedios de sentiment, pero sí se cuentan en el bloque de calidad
   de datos del dashboard.
