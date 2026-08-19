import os
from dotenv import load_dotenv

load_dotenv()

# DataForSEO
DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")

# Apify
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Proyecto
BRAND_KEYWORD = os.getenv("BRAND_KEYWORD", "Avianca")
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "CO")
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "es")
LOCATION_CODE = int(os.getenv("LOCATION_CODE", "2170"))

# Apify actor IDs (no cambiar)
APIFY_INSTAGRAM_ACTOR = "apify/instagram-scraper"
APIFY_TIKTOK_ACTOR = "clockworks/tiktok-scraper"
APIFY_TWITTER_ACTOR = "apidojo/tweet-scraper"

# Límites por scraper por ejecución
LIMIT_DATAFORSEO = 100
LIMIT_INSTAGRAM = 50
LIMIT_TIKTOK = 50
LIMIT_TWITTER = 100

# Perfiles de Instagram por marca
INSTAGRAM_PROFILES = {
    "Avianca": [
        "https://www.instagram.com/avianca/",
        "https://www.instagram.com/aviancacolombia/",
    ],
    "LATAM": [
        "https://www.instagram.com/latam_airlines/",
        "https://www.instagram.com/latamcolombia/",
    ],
}

# Dominios oficiales a excluir por marca
BRAND_DOMAINS = {
    "Avianca": {
        "avianca.com", "www.avianca.com", "help.avianca.com",
        "newsroom.avianca.com", "blog.avianca.com",
        "lifemiles.com", "www.lifemiles.com",
    },
    "LATAM": {
        "latamairlines.com", "www.latamairlines.com",
        "multiplus.com.br", "latampass.com",
        "newsroom.latamairlines.com",
    },
}

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
    "tidal", "atoallinks", "idealo",
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
