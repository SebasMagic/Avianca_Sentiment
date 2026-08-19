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
from pipeline.excel_writer import export as export_excel


def run_pipeline():
    print(f"\n{'='*50}")
    print(f"[Pipeline] Iniciando: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*50}\n")

    all_mentions = []

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

    normalized = normalize(all_mentions)
    enriched = enrich_sentiment(normalized)
    saved = write_mentions(enriched)
    excel_path = export_excel(enriched)

    summary = get_summary()
    print(f"\n{'='*50}")
    print(f"[Pipeline] Completado: {saved} nuevas menciones guardadas")
    print(f"[Pipeline] Excel: {excel_path}")
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
