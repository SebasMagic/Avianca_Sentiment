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
