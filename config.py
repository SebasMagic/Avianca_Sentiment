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

# Prensa (scrapers/dataforseo_news.py) y reseñas (scrapers/
# dataforseo_reviews.py) — "depth" que se pide en cada llamada.
# Verificado con datos reales (2026-08-21/22): depth=20 en Google News
# devuelve ~20 noticias repartidas entre un bloque top_stories y
# elementos news_search sueltos, por $0,004; depth=20 en Trustpilot
# reviews trae hasta 20 reseñas por $0,00075 (task_post — el task_get
# posterior es gratis). Ninguno de los dos soporta paginar por fecha del
# lado del servidor — el filtro por `since` se aplica del lado del
# cliente en ambos scrapers, igual que ya hace apify_tiktok.py.
LIMIT_NEWS = 20
LIMIT_REVIEWS = 20

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
        # Dominio propio en Trustpilot — scrapers/dataforseo_reviews.py
        # (business_data/trustpilot/reviews/task_post). Verificado contra
        # la API real (2026-08-21): avianca.com tiene 1.884 reseñas en
        # Trustpilot, rating agregado 1,2/5. Explícito en el perfil (no
        # derivado de `domains`, que trae variantes con www/subdominios)
        # para que el scraper nunca tenga que adivinar cuál de esas
        # entradas es el dominio raíz que Trustpilot espera.
        "review_domain": "avianca.com",
        "tiktok_hashtags": ["avianca", "aviancacolombia"],
        # Cuentas oficiales de TikTok — comparadas en minúsculas contra
        # authorMeta.name del video (ver pipeline/relevance.py, filtro de
        # hashtag). "aviancaoficial" es la única verificada contra datos
        # reales de Apify (2026-08-20): verified=True, 233.600 seguidores,
        # bio "¡Bienvenid@ a la nueva avianca!". "avianca" y
        # "aviancacolombia" no aparecieron todavía como autor de ningún
        # video en la base, pero son los mismos handles que ya se usan
        # como perfil de Instagram y como hashtag de esta marca — se
        # incluyen por si el actor los trae en una corrida futura, sin
        # inventar ninguno nuevo.
        "tiktok_official_accounts": {"avianca", "aviancacolombia", "aviancaoficial"},
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
        # Dominio propio en Trustpilot — ver comentario equivalente en
        # Avianca. Verificado contra la API real (2026-08-21):
        # latamairlines.com tiene 48 reseñas en Trustpilot, rating
        # agregado 1,6/5.
        "review_domain": "latamairlines.com",
        # "latam" a secas queda FUERA a propósito: es la abreviatura de
        # Latinoamérica, no solo el nombre de la aerolínea. En el backfill se
        # revisaron a mano los videos que trajo y solo 1 de 29 hablaba de la
        # aerolínea — el resto eran memes regionales, sismos y geografía.
        # Un hashtag que aporta 3% de señal contamina más de lo que suma.
        "tiktok_hashtags": ["latamairlines", "latamcolombia"],
        # Cuentas oficiales de TikTok — ver comentario equivalente en
        # Avianca. "latam_colombia" es la única verificada contra datos
        # reales de Apify (2026-08-20): verified=True, 57.600 seguidores,
        # bio "¡Hola Colombia! Bienvenido a ir más alto". "latamairlines"
        # y "latamairlines_colombia" son los mismos handles del perfil de
        # Instagram de esta marca — se incluyen por si el actor los trae
        # como autor de un video en una corrida futura.
        "tiktok_official_accounts": {
            "latamairlines", "latamairlines_colombia", "latamcolombia", "latam_colombia",
        },
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

# Razón de exclusion_reason (store/db.py) para el retiro del canal web
# (Cambio 1) — ver scrapers/dataforseo_scraper.py y pipeline/
# web_channel_retirement.py. Constante compartida entre el módulo que marca
# las filas y dashboard/aggregate.py, que la usa para separar el conteo de
# "canal retirado" del de "irrelevancia social" (exclusion_reason de TikTok)
# en el bloque 8 — son dos motivos de exclusión distintos y el reporte los
# explica por separado, no mezclados bajo un solo texto.
WEB_CHANNEL_RETIREMENT_REASON = "canal_web_retirado"

# Drivers operativos de queja — el LLM debe devolver exactamente uno de estos.
# El ORDEN de esta lista es solo de declaración/validación (normalize_result
# comprueba pertenencia, no precedencia) y NO es el orden de desempate cuando
# una queja encaja en varios drivers a la vez. Ese orden de precedencia vive
# en build_system_prompt(), en pipeline/classifier.py, y es distinto de este:
# cancelacion > demora > equipaje > mascotas > reembolsos > cobros_tarifas >
# fraude_publicidad > programa_fidelidad > asientos_comida > atencion_cliente
# > rechazo_marca > otro.
#
# "programa_fidelidad" (antes "lifemiles"): renombrado porque el driver es
# genérico entre marcas — Avianca tiene LifeMiles, LATAM tiene LATAM Pass.
# El nombre del programa que ve el LLM sale de brand["loyalty_program"],
# inyectado en el prompt por build_system_prompt().
#
# "mascotas", "fraude_publicidad", "rechazo_marca" (nuevos — descubrimiento
# sobre "otro", ver .superpowers/otro-y-web.md): "otro" era el driver #1 en
# Avianca (202 quejas, 28,7% en el reporte) — una caja negra. Se pasaron las
# ~368 quejas de "otro" de ambas marcas (305 Avianca + 63 LATAM) por
# DeepSeek en lotes, pidiéndole que descubriera y nombrara los temas sin
# categorías predefinidas (codebook evolutivo entre lotes, para converger en
# nombres consistentes). Resultado, con volumen verificado:
#   - Rechazo/insultos a la marca sin causa operativa (248/368, 67%): el
#     grupo más grande, confirma la hipótesis del usuario — es legítimamente
#     inespecífico, pero merece nombre propio en vez de perderse en "otro".
#     → "rechazo_marca".
#   - Mascotas/animales a bordo (~28/368): pérdida, maltrato o política de
#     transporte de mascotas — volumen propio, causa identificable y
#     accionable (política de mascotas). → "mascotas".
#   - Fraude/publicidad engañosa (~21/368): páginas o perfiles falsos que
#     suplantan la marca para estafar, y publicidad propia que el usuario
#     considera engañosa — accionable (seguridad de marca / comunicaciones).
#     → "fraude_publicidad".
# Temas insinuados en el vistazo manual que SÍ se verificaron pero NO
# alcanzaron volumen propio (se quedan en "otro", no ganan driver): amenazas
# legales (~7/368), fallas de app/canales digitales (~6/368), solicitudes de
# rutas nuevas o de vuelos de ayuda humanitaria (~30/368 — más bien
# peticiones que quejas de servicio, ver build_system_prompt). "Denegación
# de embarque", también insinuada, se buscó explícitamente en TODAS las
# quejas (no solo "otro") y no apareció con volumen real (1-2 voces únicas)
# — la hipótesis inicial no se sostuvo, y no se crea driver para ella.
COMPLAINT_DRIVERS = [
    "equipaje",
    "cancelacion",
    "demora",
    "atencion_cliente",
    "cobros_tarifas",
    "programa_fidelidad",
    "asientos_comida",
    "reembolsos",
    "mascotas",
    "fraude_publicidad",
    "rechazo_marca",
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

# Vocabulario de contexto aeronáutico — usado por pipeline/relevance.py
# para decidir si un resultado de búsqueda por HASHTAG (TikTok) habla de
# verdad de la aerolínea o solo contiene el nombre de la marca por
# coincidencia (ver docstring de is_relevant y el caso real de "#latam":
# 28 de 29 videos eran memes de Latinoamérica, geografía o K-pop que ni
# por asomo hablaban de volar).
#
# Formas ya en minúscula y SIN tilde — pipeline/relevance.py le quita los
# acentos al texto antes de comparar (unicodedata NFKD), así que
# "cancelación" y "cancelacion" son la misma entrada acá ("cancelacion")
# y no hace falta duplicar cada palabra con y sin tilde. Cuando dos
# idiomas usan palabras genuinamente distintas (no una variante de
# acentuación de la misma palabra: avión/avião, aerolinea/companhia
# aerea/airline, equipaje/bagagem/luggage) sí se listan todas por
# separado.
#
# Cubre español, portugués e inglés — el dataset tiene los tres (el
# ejemplo que sí es relevante en "#latam" está en portugués: "Como foi
# minha experiência voando com a latam").
#
# La lista base (vuelo/volar/avión/aerolínea/equipaje/aeropuerto/check-in/
# abordaje/escala/piloto/tripulación/asiento/tiquete/millas/cancelación/
# reembolso/sobrecargo/terminal/puerta) salió del enunciado de la tarea.
# Calibrando contra los hashtags reales #avianca/#aviancacolombia (ver
# .superpowers/relevancia-social.md) se encontró que esa lista, con
# equivalentes en un solo idioma para varios conceptos, descartaba
# contenido real de la marca que sí hablaba de volar pero en inglés —
# "Avianca flight attendant...", "...SEAT EXPERIENCE...", "...Avianca
# Pilot clarifies...", "psa if you are traveling... #avianca" — porque
# "flight", "seat", "pilot" (inglés) no tenían equivalente en la lista
# aunque "piloto"/"asiento" (español) sí. Las líneas de abajo agregan el
# equivalente que faltaba por idioma para esos mismos conceptos (no
# conceptos nuevos), más "pasajero/passenger/passageiro" (pasajero no
# estaba en el enunciado pero es evidentemente aeronáutico y apareció
# repetido en contenido real de tripulación) y "aéreo/aviación/aviation/
# aviação" (adjetivo/sustantivo genérico de aviación, de riesgo muy bajo
# de falso positivo y que también apareció en contenido real descartado
# por error). Todo sigue siendo comparación por PALABRA COMPLETA
# (word-boundary vía tokenización, ver _has_aviation_context) — nunca
# substring — así que términos cortos como "milla"/"miles" no capturan
# "sonríe"/"smiles" ni "escala" captura "escalator".
AVIATION_CONTEXT_WORDS = {
    "vuelo", "vuelos", "flight", "flights",
    "volar", "volando", "voando", "voo", "voos", "fly", "flying",
    "avion", "aviones", "aviao", "avioes", "plane", "planes", "airplane", "airplanes",
    "aerolinea", "aerolineas", "airline", "airlines",
    "equipaje", "equipajes", "maleta", "maletas", "bagagem", "bagagens",
    "luggage", "baggage",
    "aeropuerto", "aeropuertos", "aeroporto", "aeroportos", "airport", "airports",
    "checkin",
    "abordaje", "boarding",
    "escala", "escalas", "layover", "stopover",
    "piloto", "pilotos", "pilot", "pilots",
    "tripulacion", "tripulantes", "tripulacao", "crew",
    "asiento", "asientos", "assento", "assentos", "seat", "seats",
    "tiquete", "tiquetes", "pasaje", "pasajes", "boleto", "boletos",
    "passagem", "passagens", "ticket", "tickets",
    "pasajero", "pasajeros", "passageiro", "passageiros", "passenger", "passengers",
    "milla", "millas",
    "cancelacion", "cancelamento", "cancelled", "canceled", "cancellation", "cancellations",
    "reembolso", "reembolsos", "refund", "refunds",
    "sobrecargo", "sobrecargos", "azafata", "azafatas",
    "terminal", "terminales",
    "puerta", "puertas", "portao", "portoes",
    "aereo", "aerea", "aereos", "aereas",
    "aviacion", "aviacao", "aviation",
}

# Términos de más de una palabra — no pueden vivir en AVIATION_CONTEXT_WORDS
# porque esa se compara palabra por palabra (ver _has_aviation_context).
# Se buscan como substring del texto ya sin tildes; "check-in"/"check in"
# se normalizan aparte a "checkin" (ver relevance.py) y por eso ya caen en
# la lista de arriba, no acá.
AVIATION_CONTEXT_PHRASES = {
    "companhia aerea",
}

# Subconjunto de AVIATION_CONTEXT_WORDS seguro para buscar como SUBSTRING
# dentro de cada hashtag individual (no del texto completo — ver
# _has_aviation_context) — para los hashtags de TikTok que llegan pegados
# sin espacio, verificados en datos reales: "#latamairlines" (reseña real:
# "Reliable and good quality! ... #LATAMairlines #airlinereview"),
# "#aviancaairlines", "#flightattendant", "#airlinereview". Un match
# exacto de token nunca los detecta.
#
# Curado a mano: cada término de acá se revisó buscando si es substring de
# alguna palabra común NO aeronáutica antes de incluirlo. Términos de
# AVIATION_CONTEXT_WORDS que SÍ colisionan como substring se dejan FUERA
# de este subconjunto a propósito (solo cuentan si aparecen como palabra
# completa, arriba):
#   "milla"/"miles"  → substring de "sonríe"/"smiles", "milestone"
#   "escala"         → substring de "escalador", "escalada", "escalator"
#   "crew"           → substring de "screw"
#   "boarding"       → substring de "skateboarding", "snowboarding"
#   "checkin"        → substring de "checking"
#   "plane"          → substring de "planeta", "planeación"
#   "gate"           → ni siquiera está en AVIATION_CONTEXT_WORDS por esto
AVIATION_CONTEXT_SUBSTRING_TERMS = {
    "flight", "vuelo", "avion", "aereo", "aerolinea", "airline", "aviacion", "aviation",
    "equipaje", "luggage", "baggage", "maleta",
    "aeropuerto", "aeroporto", "airport",
    "piloto", "pilot",
    "tripulacion", "azafata", "sobrecargo",
    "asiento", "assento", "seat",
    "tiquete", "pasaje", "boleto", "ticket", "passagem",
    "pasajero", "passenger", "passageiro",
    "reembolso", "refund",
    "cancelacion", "cancelled", "canceled", "cancelamento",
    "terminal",
    "puerta", "portao",
}

# Medios reconocidos — usado por pipeline/relevance.py para la rama
# "prensa" de is_relevant(). Match por etiqueta de dominio (misma técnica
# que BLACKLIST_DOMAIN_ROOTS): "eltiempo" atrapa www.eltiempo.com sin
# atrapar nada más.
#
# Regla completa (pedida por el usuario, calcada de la de hashtag de
# TikTok): una nota de prensa es relevante si (a) viene de uno de estos
# dominios, SIN exigir además contexto aeronáutico en el texto — igual
# que una cuenta oficial de TikTok no necesita esa palabra — o (b) el
# texto menciona la marca Y contiene contexto aeronáutico.
#
# Por qué la rama (a) es necesaria y no basta con (b): verificado con
# datos reales (2026-08-21/22, ver .superpowers/prensa-resenas.md). Para
# "Avianca" (nombre propio sin ambigüedad) la keyword sola casi nunca
# falla. Para "LATAM" SÍ hay ambigüedad real — es también la abreviatura
# de Latinoamérica — y una búsqueda de noticias por "LATAM" trajo, el
# mismo día, tanto cobertura real de la aerolínea (Portafolio: "Latam
# fija precios máximos"; Blu Radio: "LATAM transporta ayuda al Chocó")
# como ruido total sin relación (3tres3.com sobre porcicultura, ONU
# Mujeres, un sindicato). Algunas notas genuinas sobre la aerolínea
# (Blu Radio, Valora Analitik) no usan ninguna palabra de
# AVIATION_CONTEXT_WORDS en su título/snippet ("transporta ayuda",
# "transporta... mango") — sin la rama de dominio reconocido, esas notas
# reales se habrían descartado como si no dijeran nada de la aerolínea.
#
# Deliberadamente NO es "cualquier medio nacional grande": en la misma
# corrida de LATAM, forbes.co trajo una nota sobre IA antifraude sin
# relación con la aerolínea. Un dominio entra a esta lista solo si, en
# los datos verificados, sus notas SOBRE la marca fueron genuinamente
# sobre la aerolínea — no basta con ser un medio serio en general. Un
# dominio que hoy no está aquí simplemente cae a la rama (b): sigue
# pudiendo pasar si su texto trae contexto aeronáutico explícito.
RECOGNIZED_MEDIA_DOMAINS = {
    "eltiempo", "caracol", "elespectador", "semana", "portafolio",
    "elcolombiano", "infobae", "elheraldo", "publimetro",
    "asuntoslegales", "bluradio", "reportur",
}

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
