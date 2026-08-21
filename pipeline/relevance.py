"""
Filtro de relevancia para menciones web y para contenido social de
HASHTAG.

Responde una sola pregunta por plataforma: ¿esta mención habla de la
marca-la-aerolínea, o es ruido?

Función pura: sin red, sin DB, sin estado.

Regla por PROCEDENCIA (no por plataforma a secas — corregido tras
verificar 29 videos reales de "#latam", ver docstring de is_relevant):

  - Contenido que vive en un post PROPIO de la marca — comentarios de
    Instagram (Fase 2, sobre los perfiles oficiales de brand["instagram_
    profiles"]) — NO se filtra. El contexto ya garantiza que hablan de
    ella: no hay forma de comentar un post de @avianca sin que ese post
    sea de Avianca. Filtrar ahí solo descartaría quejas cortas legítimas
    ("me perdieron la maleta", sin la palabra "Avianca" ni "equipaje"
    explícitos) sin ganar nada a cambio.
  - Contenido que es resultado de una búsqueda por HASHTAG — hoy, TikTok
    completo: apify_tiktok.py no tiene otra forma de traer contenido, así
    que TODO lo que llega con platform="tiktok" es, por construcción, un
    resultado de búsqueda de brand["tiktok_hashtags"] — SÍ se filtra. Un
    hashtag es una coincidencia de texto sobre cualquier tema; el
    contexto NO está garantizado (ver el caso real de "#latam" en el
    docstring de is_relevant).

`brand` (el perfil de config.BRANDS / config.get_brand) se recibe como
parámetro en cada llamada, nunca se resuelve a nivel de módulo — antes
`_BRAND_DOMAINS` se calculaba una sola vez al importar, a partir de un
BRAND_KEYWORD fijo leído del entorno, así que un mismo proceso no podía
filtrar Avianca y LATAM en la misma corrida.
"""
import re
import unicodedata

from config import (
    AVIATION_CONTEXT_PHRASES,
    AVIATION_CONTEXT_SUBSTRING_TERMS,
    AVIATION_CONTEXT_WORDS,
    BLACKLIST_DOMAIN_ROOTS,
    LANG_MIN_STOPWORDS,
    LANG_MIN_WORDS,
    SPANISH_STOPWORDS,
)

_WORD_RE = re.compile(r"[a-záéíóúñü]+")
_ASCII_WORD_RE = re.compile(r"[a-z]+")


def is_spanish(text: str) -> bool:
    """
    Heurística sin dependencias: cuenta stopwords españolas distintas.

    Los textos de menos de LANG_MIN_WORDS palabras se dan por válidos —
    son demasiado cortos para decidir, y el filtro de keyword los cubre.
    """
    words = _WORD_RE.findall(text.lower())
    if len(words) < LANG_MIN_WORDS:
        return True
    hits = {w for w in words if w in SPANISH_STOPWORDS}
    return len(hits) >= LANG_MIN_STOPWORDS


def _is_blacklisted(domain: str) -> bool:
    """
    Match por etiqueta de dominio, no por string completo.
    Así una sola entrada "rehlat" atrapa rehlat.es, au.rehlat.com y www.rehlat.mx.
    """
    return any(label in BLACKLIST_DOMAIN_ROOTS for label in domain.split("."))


def _strip_accents(text: str) -> str:
    """NFKD + descartar los caracteres combinantes: "aérea"→"aerea",
    "canción"→"cancion". Usado solo por el filtro de contexto aeronáutico
    — is_spanish() sigue intacta, con su propio criterio basado en tildes."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _has_aviation_context(text: str) -> bool:
    """
    True si `text` contiene alguna palabra o frase de config.AVIATION_
    CONTEXT_WORDS/PHRASES — en español, portugués o inglés, sin importar
    tildes ("cancelación" y "cancelacion" cuentan igual).

    "check-in"/"check in" se normalizan a "checkin" ANTES de tokenizar
    para que caigan en AVIATION_CONTEXT_WORDS como una sola palabra — sin
    esto, el guion las partiría en "check" e "in", y "in" es una palabra
    demasiado común en inglés para usarla como señal por sí sola.

    Segunda pasada, por TOKEN (nunca sobre el texto completo): busca
    AVIATION_CONTEXT_SUBSTRING_TERMS como substring DENTRO de cada hashtag
    individual — verificado con datos reales de TikTok, donde el hashtag
    llega pegado sin espacio ("#latamairlines", "#aviancaairlines",
    "#flightattendant") y el match exacto de palabra completa nunca lo
    detecta. Restringido a un subconjunto chico y ya revisado por
    colisión (ver comentario junto a AVIATION_CONTEXT_SUBSTRING_TERMS en
    config.py) — nunca se hace substring con la lista completa, que sí
    tiene términos cortos riesgosos ("miles" dentro de "smiles", "escala"
    dentro de "escalator").
    """
    normalized = _strip_accents(text or "").lower()
    normalized = normalized.replace("check-in", "checkin").replace("check in", "checkin")

    tokens = _ASCII_WORD_RE.findall(normalized)
    if set(tokens) & AVIATION_CONTEXT_WORDS:
        return True

    if any(term in token for token in tokens for term in AVIATION_CONTEXT_SUBSTRING_TERMS):
        return True

    return any(phrase in normalized for phrase in AVIATION_CONTEXT_PHRASES)


def _is_official_hashtag_account(author: str | None, brand: dict) -> bool:
    """
    True si `author` (el handle que publicó el video, ya en minúsculas)
    es una cuenta oficial de la marca — brand["tiktok_official_accounts"],
    verificadas contra datos reales de Apify (ver config.py), nunca
    sueltas dentro de este módulo. Un video propio de la marca que
    aparece en un resultado de hashtag no necesita mencionar contexto
    aeronáutico explícito para ser relevante — la cuenta que lo publicó
    ya lo garantiza, el mismo argumento que exime a los comentarios de
    Instagram.
    """
    if not author:
        return False
    handles = brand.get("tiktok_official_accounts") or set()
    return author.strip().lower() in handles


def _is_hashtag_relevant(mention: dict, brand: dict) -> tuple[bool, str]:
    """
    Relevancia de un resultado de búsqueda por hashtag (hoy: TikTok).
    Relevante si se cumple alguna de:

      1. Lo publicó una cuenta oficial de la marca (ver
         _is_official_hashtag_account).
      2. El texto menciona la marca (brand["keyword"]) Y además contiene
         algún término de contexto aeronáutico (_has_aviation_context) —
         un chequeo de keyword solo no alcanza: el video de K-pop del
         caso real de "#latam" contiene literalmente "latam" en su
         descripción sin hablar ni remotamente de la aerolínea.
    """
    if _is_official_hashtag_account(mention.get("author"), brand):
        return True, ""

    text = mention.get("text") or ""
    keyword = (brand.get("keyword") or "").lower()
    if keyword and keyword not in text.lower():
        return False, "sin_keyword"

    if not _has_aviation_context(text):
        return False, "sin_contexto_aeronautico"

    return True, ""


def is_relevant(mention: dict, brand: dict) -> tuple[bool, str]:
    """
    Devuelve (pasa, razon_de_descarte).
    razon es "" cuando pasa.

    `brand` aporta "domains"/"keyword" (marca web), "tiktok_official_
    accounts" (marca hashtag) — todos específicos de la marca que se está
    procesando en esta llamada, nunca un default global. El mismo dominio
    puede ser oficial para una marca y no para otra (p.ej.
    www.latamairlines.com es oficial de LATAM, irrelevante para el filtro
    de Avianca).

    Por plataforma:
      - "web": filtro completo (dominio oficial, agregador/OTA, idioma,
        keyword) — sin cambios.
      - "tiktok": filtro de hashtag (ver _is_hashtag_relevant) — Tarea 1/2
        de la corrección de relevancia social. Caso real que motivó esto:
        el hashtag "#latam" trajo 29 videos, de los cuales 28 eran ruido
        —memes sobre Latinoamérica, quizzes de geografía, K-pop, sismos,
        fútbol, acentos, Undertale— y solo 1 hablaba de la aerolínea (una
        reseña de vuelo en portugués). Un chequeo de keyword solo no
        distingue esos casos porque el video de K-pop también contiene
        "latam" en su texto — hace falta contexto aeronáutico además del
        nombre de la marca.
      - cualquier otra ("instagram", y cualquier plataforma futura que no
        sea resultado de hashtag): pasa sin evaluar. Instagram en este
        pipeline es siempre comentarios de Fase 2 sobre los perfiles
        oficiales de la marca (brand["instagram_profiles"]) — el post
        contenedor ya garantiza el contexto, filtrar ahí solo
        descartaría quejas cortas legítimas.
    """
    platform = mention.get("platform")

    if platform == "web":
        domain = (mention.get("author") or "").lower().strip()

        if domain in brand["domains"]:
            return False, "dominio_oficial"

        if _is_blacklisted(domain):
            return False, "agregador"

        text = mention.get("text") or ""

        if not is_spanish(text):
            return False, "idioma"

        if brand["keyword"].lower() not in text.lower():
            return False, "sin_keyword"

        return True, ""

    if platform == "tiktok":
        return _is_hashtag_relevant(mention, brand)

    return True, ""
