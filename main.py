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
