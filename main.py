"""
main.py — Entry point del pipeline Avianca/LATAM Sentiment Monitor v2.

  python main.py                                # corrida semanal (since incremental), marca por defecto
  python main.py --brand LATAM                  # corrida semanal para LATAM
  python main.py --since 2026-08-10             # corrida semanal desde una fecha explícita
  python main.py --backfill                     # backfill desde config.BACKFILL_SINCE
  python main.py --backfill --since 2026-04-19  # backfill desde una fecha
  python main.py --seed-excel v1.xlsx           # importa el Excel del v1
  python main.py --classify                     # solo reclasifica lo pendiente
  python main.py --export-excel                 # vuelca la DB a .xlsx
  python main.py --enriquecer-engagement         # puebla saves/views desde el raw ya guardado
  python main.py --enriquecer-instagram-reach    # backfill de alcance de posts de Instagram (gasta Apify)
  python main.py --backfill-cuenta-origen --brand LATAM  # cuenta de origen para IG ya en la DB (gasta poco Apify)
  python main.py --solo-instagram --since 2026-01-01  # re-corre SOLO Instagram, sin re-pagar TikTok
  python main.py --solo-prensa --brand LATAM     # re-corre SOLO prensa (Google News, gasta poco)
  python main.py --solo-resenas --brand LATAM    # re-corre SOLO reseñas (Trustpilot, gasta poco)
  python main.py --limpiar-relevancia-social --brand LATAM  # aplica el filtro de hashtag a TikTok ya en la DB (no gasta API)
  python main.py --retirar-canal-web --brand LATAM  # marca las menciones web ya en la DB como excluidas (no gasta API)
  python main.py --schedule                     # semanal, lunes 8am

`--brand` (default: config.DEFAULT_BRAND = "Avianca") acota TODO el
comando a una sola marca: qué se scrapea, con qué prompt se clasifica, y
qué filas se leen/escriben en la DB (la capa de datos es multi-marca, ver
config.BRANDS — el dashboard sigue siendo de una marca a la vez, mezclar
vistas es trabajo aparte). Falla temprano con un mensaje claro si la
marca no existe en config.BRANDS.

Twitter/X queda fuera de v2: el actor de Apify con búsqueda histórica
por rango de fechas es de pago. scrapers/apify_twitter.py se conserva
pero no está en SCRAPERS.

DataForSEO (canal web) queda fuera también (Cambio 1, decisión del
usuario): 71 menciones web entre Avianca y LATAM producen solo 2 quejas
reales, y desde el diagnóstico inicial esta capa es ~95% agregadores de
vuelos — el resto de la muestra revisada a mano trajo un casino online,
una página de registro de eventos, un directorio de empresas, spam SEO y
granjas de teléfonos falsos suplantando el call center. No es conversación
de aerolíneas. scrapers/dataforseo_scraper.py se conserva (ver su
docstring) pero no está en SCRAPERS; las menciones web YA guardadas se
retiraron con --retirar-canal-web (pipeline/web_channel_retirement.py),
que las marca con exclusion_reason sin borrarlas.

Corrida `weekly` (sin --since explícito): NO usa un rolling fijo de 7
días. `since` se calcula como la fecha de inicio de la última corrida
TERMINADA menos un día de margen (para no perder nada en el borde); si
no hay corrida previa, cae a 7 días atrás. Ver compute_weekly_since().
Sin esto, el filtro de fecha de Instagram quedaría deshabilitado por
completo (since=None) — cada corrida "semanal" se comportaría como un
mini-backfill repetido, pagando el costo completo de Apify cada vez.

`--solo-instagram`: acota `SCRAPERS` a un único elemento (Instagram) antes
de llamar a run_pipeline(). Existe para re-correr Instagram tras subir
config.INSTAGRAM_POSTS_LIMIT (o cualquier otro cambio que solo afecte a
ese scraper) sin volver a pagar TikTok, que ya corrió y cuyos resultados
ya están en la DB. El dedup por fingerprint hace que re-correr sea
seguro: lo ya visto se ignora (INSERT OR IGNORE), solo se suma lo nuevo.

`--solo-prensa`/`--solo-resenas`: mismo patrón que `--solo-instagram`,
para scrapers/dataforseo_news.py y scrapers/dataforseo_reviews.py
respectivamente. Prensa y reseñas NO están en el SCRAPERS por defecto
(igual que "web" — ver el comentario de DataForSEO más abajo, aunque acá
la razón es otra: cuestan poco pero cuestan, y una corrida `weekly`
normal no debería gastar en ellas sin que alguien lo pida explícitamente;
a diferencia del canal web, esta decisión no es "las descartamos", es
"las corremos a propósito, no de rebote"). Se corren con estos flags
(o llamando run_pipeline con scrapers=[...] a mano) para las dos marcas.
"""
import argparse
import collections
import time
from datetime import datetime, timedelta, timezone

import schedule

from config import BACKFILL_SINCE, DEFAULT_BRAND, get_brand
from pipeline import (
    classify_pending, engagement_enrichment, instagram_reach_backfill,
    social_relevance_backfill, source_account_backfill, web_channel_retirement,
)
from pipeline.excel_writer import export as export_excel
from pipeline.normalizer import normalize
from pipeline.relevance import is_relevant
from scrapers import apify_instagram, apify_tiktok, dataforseo_news, dataforseo_reviews
from store import db, seed_excel

SCRAPERS = [
    ("Instagram", apify_instagram.scrape),
    ("TikTok", apify_tiktok.scrape),
]

WEEKLY_LOOKBACK_DAYS = 7
WEEKLY_MARGIN_DAYS = 1


def compute_weekly_since(conn, now: datetime | None = None) -> str:
    """
    `since` de una corrida `weekly` cuando no se pasó --since explícito.

    since = fecha de inicio (started_at) de la última corrida TERMINADA,
    menos un día de margen para no perder nada en el borde. Si no hay
    corrida previa, 7 días atrás. Apoyarse en la última corrida real (y
    no en un rolling fijo) evita abrir huecos si una semana se salta.
    """
    now = now or datetime.now(timezone.utc)
    last_started = db.last_completed_run_started_at(conn)
    if last_started:
        base = datetime.fromisoformat(last_started)
        since_date = base - timedelta(days=WEEKLY_MARGIN_DAYS)
    else:
        since_date = now - timedelta(days=WEEKLY_LOOKBACK_DAYS)
    return since_date.strftime("%Y-%m-%d")


def run_pipeline(mode: str = "weekly", since: str | None = None,
                  brand_name: str = DEFAULT_BRAND,
                  scrapers: list[tuple[str, "callable"]] | None = None) -> dict:
    """
    `scrapers`: lista [(nombre, scrape_fn), ...] a ejecutar en esta corrida.
    None (default) usa el módulo SCRAPERS completo (comportamiento
    histórico). `main()` pasa un subconjunto acotado a Instagram cuando se
    invoca con `--solo-instagram` — ver docstring del módulo.
    """
    conn = db.connect()
    brand = get_brand(brand_name)  # falla temprano y claro si la marca no existe
    active_scrapers = scrapers if scrapers is not None else SCRAPERS

    # --since explícito siempre gana; solo se calcula si no se pasó nada.
    if mode == "weekly" and since is None:
        since = compute_weekly_since(conn)

    print(f"\n{'=' * 56}")
    print(f"[Pipeline] {mode} | brand={brand_name} | since={since or '—'} | "
          f"{datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 56}\n")

    run_id = db.start_run(conn, mode, since, brand=brand_name)

    raw = []
    errores = []
    for nombre, scrape_fn in active_scrapers:
        try:
            raw.extend(scrape_fn(brand, since=since))
        except Exception as e:
            print(f"[{nombre}] ERROR: {e}")
            errores.append(f"{nombre}: {e}")

    print(f"\n[Pipeline] Total crudo: {len(raw)} menciones")

    # Cada mención producida por esta corrida queda etiquetada con su marca
    # antes de normalizar/filtrar/insertar — así el fingerprint y la
    # columna `brand` de `mentions` la reflejan correctamente.
    for m in raw:
        m["brand"] = brand_name

    normalizadas = normalize(raw)
    # normalize() descarta silenciosamente los textos de menos de
    # MIN_TEXT_LENGTH caracteres (comentarios de solo emoji) antes de que
    # corra el filtro de relevance — por eso no aparecen en filtered_count.
    # Sin este contador, esas menciones desaparecían sin dejar rastro en
    # ningún campo de `runs` (Important #2 de la revisión).
    short_text_count = len(raw) - len(normalizadas)

    razones = collections.Counter()
    keep = []
    for m in normalizadas:
        ok, razon = is_relevant(m, brand)
        if ok:
            keep.append(m)
        else:
            razones[razon] += 1

    if razones:
        print(f"[Relevance] descartadas: {dict(razones)}")

    inserted, duplicates = db.upsert_mentions(conn, keep, run_id)
    print(f"[Store] {inserted} nuevas, {duplicates} ya existían")

    clasificacion = classify_pending.run(conn, brand)

    db.finish_run(
        conn, run_id,
        raw_count=len(raw),
        filtered_count=len(normalizadas) - len(keep),
        inserted_count=inserted,
        duplicate_count=duplicates,
        short_text_count=short_text_count,
        notes="; ".join(errores),
    )

    total = conn.execute(
        "SELECT COUNT(*) FROM mentions WHERE brand = ?", (brand_name,)
    ).fetchone()[0]
    conn.close()

    print(f"\n{'=' * 56}")
    print(f"[Pipeline] Completado. Total acumulado en DB para {brand_name}: {total}")
    print(f"{'=' * 56}\n")

    return {
        "raw": len(raw),
        "inserted": inserted,
        "duplicates": duplicates,
        "total": total,
        **clasificacion,
    }


def main():
    parser = argparse.ArgumentParser(description="Avianca/LATAM Sentiment Monitor v2")
    parser.add_argument("--brand", default=DEFAULT_BRAND,
                        help=f"marca a procesar (default: {DEFAULT_BRAND}; ver config.BRANDS)")
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
    parser.add_argument("--enriquecer-engagement", action="store_true",
                        help="puebla saves/views/reach_source desde el raw ya guardado (sin llamar APIs)")
    parser.add_argument("--enriquecer-instagram-reach", action="store_true",
                        help="backfill de alcance (views) de los posts de Instagram ya en la DB "
                             "(1 llamada de Fase 1 a Apify — gasta unos centavos)")
    parser.add_argument("--schedule", action="store_true",
                        help="corre cada lunes a las 8am")
    parser.add_argument("--solo-instagram", action="store_true",
                        help="corrida (backfill o weekly) que ejecuta SOLO el scraper de "
                             "Instagram — no re-scrapea TikTok, ya pagado")
    parser.add_argument("--solo-prensa", action="store_true",
                        help="corrida que ejecuta SOLO el scraper de prensa (Google News vía "
                             "DataForSEO, scrapers/dataforseo_news.py) — gasta poco (~$0,004 "
                             "por marca), ver --brand")
    parser.add_argument("--solo-resenas", action="store_true",
                        help="corrida que ejecuta SOLO el scraper de reseñas (Trustpilot vía "
                             "DataForSEO, scrapers/dataforseo_reviews.py) — gasta poco "
                             "(~$0,00075 por marca), ver --brand")
    parser.add_argument("--backfill-cuenta-origen", action="store_true",
                        help="backfill de source_account (cuenta de Instagram del post) para "
                             "menciones YA en la DB que quedaron NULL — 1 llamada de Fase 1 a "
                             "Apify sobre los posts únicos pendientes (gasta poco, ver --brand)")
    parser.add_argument("--limpiar-relevancia-social", action="store_true",
                        help="aplica retroactivamente el filtro de relevancia de hashtag "
                             "(pipeline/relevance.py) a las menciones de TikTok YA en la DB — "
                             "no borra filas, marca exclusion_reason; no gasta API (ver --brand)")
    parser.add_argument("--retirar-canal-web", action="store_true",
                        help="marca las menciones platform='web' YA en la DB como excluidas "
                             "(pipeline/web_channel_retirement.py) — no borra filas, marca "
                             "exclusion_reason; no gasta API (ver --brand)")
    args = parser.parse_args()

    # Falla temprano y con mensaje claro si --brand no existe en config.BRANDS,
    # antes de tocar la DB o cualquier API — para cualquier subcomando.
    brand = get_brand(args.brand)

    if args.seed_excel:
        conn = db.connect()
        res = seed_excel.seed(args.seed_excel, conn, brand)
        conn.close()
        print(f"[Seed] {res}")
        return

    if args.classify:
        conn = db.connect()
        print(f"[Classify] {classify_pending.run(conn, brand)}")
        conn.close()
        return

    if args.export_excel:
        conn = db.connect()
        export_excel(db.all_mentions(conn, brand=args.brand), brand_name=args.brand)
        conn.close()
        return

    if args.enriquecer_engagement:
        conn = db.connect()
        print(f"[Engagement] {engagement_enrichment.run(conn, brand=args.brand)}")
        conn.close()
        return

    if args.enriquecer_instagram_reach:
        conn = db.connect()
        print(f"[InstagramReach] {instagram_reach_backfill.run(conn)}")
        conn.close()
        return

    if args.backfill_cuenta_origen:
        conn = db.connect()
        print(f"[SourceAccountBackfill] {source_account_backfill.run(conn, brand=args.brand)}")
        conn.close()
        return

    if args.limpiar_relevancia_social:
        conn = db.connect()
        print(f"[SocialRelevanceBackfill] {social_relevance_backfill.run(conn, brand=args.brand)}")
        conn.close()
        return

    if args.retirar_canal_web:
        conn = db.connect()
        print(f"[WebChannelRetirement] {web_channel_retirement.run(conn, brand=args.brand)}")
        conn.close()
        return

    if args.schedule:
        print(f"[Scheduler] cada lunes a las 8am hora Colombia, marca={args.brand}...")
        schedule.every().monday.at("08:00").do(run_pipeline, brand_name=args.brand)
        while True:
            schedule.run_pending()
            time.sleep(60)
        return

    if args.solo_instagram:
        scrapers_activos = [("Instagram", apify_instagram.scrape)]
    elif args.solo_prensa:
        scrapers_activos = [("Prensa", dataforseo_news.scrape)]
    elif args.solo_resenas:
        scrapers_activos = [("Reseñas", dataforseo_reviews.scrape)]
    else:
        scrapers_activos = None

    if args.backfill:
        run_pipeline("backfill", args.since or BACKFILL_SINCE, brand_name=args.brand,
                     scrapers=scrapers_activos)
    else:
        run_pipeline("weekly", args.since, brand_name=args.brand, scrapers=scrapers_activos)


if __name__ == "__main__":
    main()
