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
COUNTRY_CODE = os.getenv("COUNTRY_CODE", "CO")
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "es")
LOCATION_CODE = int(os.getenv("LOCATION_CODE", "2170"))

# Apify actor IDs (no cambiar)
APIFY_INSTAGRAM_ACTOR = "apify/instagram-scraper"
APIFY_TIKTOK_ACTOR = "clockworks/tiktok-scraper"
APIFY_TWITTER_ACTOR = "apidojo/tweet-scraper"

# Límites por scraper por ejecución. LIMIT_DATAFORSEO, LIMIT_TIKTOK y
# LIMIT_TWITTER son techos globales de la corrida. LIMIT_INSTAGRAM es la
# excepción: apify_instagram.py lo aplica POR POST (resultsLimit de la
# Fase 2, que se pide junto con directUrls=post_urls), no como techo
# global — con INSTAGRAM_POSTS_LIMIT posts (ver definición más abajo), el
# techo teórico real es INSTAGRAM_POSTS_LIMIT × LIMIT_INSTAGRAM, no
# LIMIT_INSTAGRAM solo.
LIMIT_DATAFORSEO = 100
LIMIT_INSTAGRAM = 50
LIMIT_TIKTOK = 50
LIMIT_TWITTER = 100

# Perfiles de marca — capa de datos multi-marca.
#
# Un solo diccionario reemplaza la config dispersa que existía antes
# (BRAND_KEYWORD + INSTAGRAM_PROFILES + BRAND_DOMAINS sueltos, resueltos a
# nivel de módulo en cada consumidor). Ahora cada módulo recibe el perfil
# completo de la marca como parámetro en cada llamada — nunca lo resuelve
# una sola vez al importar — para que una misma corrida pueda procesar
# Avianca y LATAM sin reiniciar el proceso.
BRANDS = {
    "Avianca": {
        "name": "Avianca",
        "keyword": "Avianca",
        "instagram_profiles": [
            "https://www.instagram.com/avianca/",
            "https://www.instagram.com/aviancacolombia/",
        ],
        "domains": {
            "avianca.com", "www.avianca.com", "help.avianca.com",
            "newsroom.avianca.com", "blog.avianca.com",
            "lifemiles.com", "www.lifemiles.com",
        },
        "tiktok_hashtags": ["avianca", "aviancacolombia"],
        "loyalty_program": "LifeMiles",
        "color": "#F62839",
        "logo": "Logo_wordmark_Avianca_(Colombia).png",
    },
    "LATAM": {
        "name": "LATAM",
        "keyword": "LATAM",
        # Handles verificados contra la API real de Apify el 2026-08-20:
        # "latam_airlines" y "latamcolombia" (los que había antes) no
        # existen — el actor los devuelve como {"error": "not_found"} en
        # la Fase 1, así que scrape() caía en "Sin posts para extraer
        # comentarios" sin ningún error visible (0 menciones de Instagram,
        # corrida "exitosa"). Los handles reales, verificados con cuenta
        # verificada y posts recientes: @latamairlines (global, 3.2M
        # seguidores) y @latamairlines_colombia (Colombia, 68K seguidores).
        "instagram_profiles": [
            "https://www.instagram.com/latamairlines/",
            "https://www.instagram.com/latamairlines_colombia/",
        ],
        "domains": {
            "latamairlines.com", "www.latamairlines.com",
            "multiplus.com.br", "latampass.com",
            "newsroom.latamairlines.com",
        },
        # "latam" a secas queda FUERA a propósito: es la abreviatura de
        # Latinoamérica, no solo el nombre de la aerolínea. En el backfill se
        # revisaron a mano los videos que trajo y solo 1 de 29 hablaba de la
        # aerolínea — el resto eran memes regionales, sismos y geografía.
        # Un hashtag que aporta 3% de señal contamina más de lo que suma.
        "tiktok_hashtags": ["latamairlines", "latamcolombia"],
        "loyalty_program": "LATAM Pass",
        "color": "#1B0088",
        "logo": None,
    },
}

DEFAULT_BRAND = "Avianca"


def get_brand(name: str) -> dict:
    """
    Perfil completo de una marca (keyword, perfiles de Instagram, dominios
    oficiales, hashtags de TikTok, programa de fidelidad, color, logo).

    Falla con un mensaje claro si `name` no está en BRANDS — mejor un
    ValueError explícito acá que un KeyError críptico más adelante, en medio
    de un scraper o del prompt del clasificador.
    """
    try:
        return BRANDS[name]
    except KeyError:
        raise ValueError(
            f"Marca desconocida: {name!r}. Marcas disponibles: {', '.join(BRANDS)}"
        ) from None

# ── v2 ────────────────────────────────────────────────────────

DB_PATH = os.getenv("DB_PATH", "data/avianca.db")

BACKFILL_SINCE = "2026-04-19"

# El dashboard reporta desde esta fecha. Las menciones anteriores siguen en la
# base pero quedan fuera del analisis: el actor de TikTok devolvio contenido de
# 2023-2025 pese a pedirle 2026, y esas 24 menciones estiraban el timeline sobre
# 41 meses con el 98% de los datos concentrados en 6.
REPORT_WINDOW_START = "2026-01-01"

# Drivers operativos de queja — el LLM debe devolver exactamente uno de estos.
# El ORDEN de esta lista es solo de declaración/validación (normalize_result
# comprueba pertenencia, no precedencia) y NO es el orden de desempate cuando
# una queja encaja en varios drivers a la vez. Ese orden de precedencia vive
# en build_system_prompt(), en pipeline/classifier.py, y es distinto de este:
# cancelacion > demora > equipaje > reembolsos > cobros_tarifas >
# programa_fidelidad > asientos_comida > atencion_cliente > otro.
#
# "programa_fidelidad" (antes "lifemiles"): renombrado porque el driver es
# genérico entre marcas — Avianca tiene LifeMiles, LATAM tiene LATAM Pass.
# El nombre del programa que ve el LLM sale de brand["loyalty_program"],
# inyectado en el prompt por build_system_prompt().
COMPLAINT_DRIVERS = [
    "equipaje",
    "cancelacion",
    "demora",
    "atencion_cliente",
    "cobros_tarifas",
    "programa_fidelidad",
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

# Instagram: cuántos posts del perfil recorrer, por marca, en la Fase 1.
#
# Era 80. Subido a 200 (2026-08-20) tras diagnosticar un sesgo de muestra
# entre marcas: Avianca publica mucho más seguido que LATAM y, con 80,
# chocaba EXACTO contra el tope — esos 80 posts solo alcanzaban a cubrir
# desde 2026-05-12 (3 meses), mientras que LATAM, con el mismo tope, ni
# siquiera lo tocaba (17 posts le bastaban para cubrir sus 4 meses
# completos, 22-abr a 20-ago). La diferencia entre marcas que parecía
# venir de los datos era en realidad el techo que nosotros mismos
# pusimos: la marca que más publica queda truncada primero, y comparar
# una ventana de 3 meses contra una de 7 no es una comparación honesta.
# 200 es suficiente para que la marca más activa (Avianca) alcance a
# cubrir REPORT_WINDOW_START (2026-01-01, ~7 meses) sin volver a chocar
# contra el tope — verificar tras cada re-corrida que el conteo de posts
# obtenidos quede por debajo de 200; si vuelve a topar, la ventana sigue
# sesgada y hay que subirlo de nuevo o acortar REPORT_WINDOW_START.
INSTAGRAM_POSTS_LIMIT = 200
