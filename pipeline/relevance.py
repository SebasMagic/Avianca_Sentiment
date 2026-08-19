"""
Filtro de relevancia para menciones web.

Responde una sola pregunta: ¿esta mención habla de Avianca-la-aerolínea,
o es ruido SEO de un agregador de vuelos?

Función pura: sin red, sin DB, sin estado. El contenido social (instagram,
tiktok) pasa directo porque ya viene de perfiles y hashtags de la marca.
"""
import re

from config import (
    BLACKLIST_DOMAIN_ROOTS,
    BRAND_DOMAINS,
    BRAND_KEYWORD,
    LANG_MIN_STOPWORDS,
    LANG_MIN_WORDS,
    SPANISH_STOPWORDS,
)

_BRAND_DOMAINS = BRAND_DOMAINS.get(BRAND_KEYWORD, set())
_WORD_RE = re.compile(r"[a-záéíóúñü]+")


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


def is_relevant(mention: dict) -> tuple[bool, str]:
    """
    Devuelve (pasa, razon_de_descarte).
    razon es "" cuando pasa.
    """
    if mention.get("platform") != "web":
        return True, ""

    domain = (mention.get("author") or "").lower().strip()

    if domain in _BRAND_DOMAINS:
        return False, "dominio_oficial"

    if _is_blacklisted(domain):
        return False, "agregador"

    text = mention.get("text") or ""

    if not is_spanish(text):
        return False, "idioma"

    if BRAND_KEYWORD.lower() not in text.lower():
        return False, "sin_keyword"

    return True, ""
