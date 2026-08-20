"""
Filtro de relevancia para menciones web.

Responde una sola pregunta: ¿esta mención habla de la marca-la-aerolínea,
o es ruido SEO de un agregador de vuelos?

Función pura: sin red, sin DB, sin estado. El contenido social (instagram,
tiktok) pasa directo porque ya viene de perfiles y hashtags de la marca.

`brand` (el perfil de config.BRANDS / config.get_brand) se recibe como
parámetro en cada llamada, nunca se resuelve a nivel de módulo — antes
`_BRAND_DOMAINS` se calculaba una sola vez al importar, a partir de un
BRAND_KEYWORD fijo leído del entorno, así que un mismo proceso no podía
filtrar Avianca y LATAM en la misma corrida.
"""
import re

from config import (
    BLACKLIST_DOMAIN_ROOTS,
    LANG_MIN_STOPWORDS,
    LANG_MIN_WORDS,
    SPANISH_STOPWORDS,
)

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


def is_relevant(mention: dict, brand: dict) -> tuple[bool, str]:
    """
    Devuelve (pasa, razon_de_descarte).
    razon es "" cuando pasa.

    `brand` aporta "domains" (dominios oficiales de esa marca, a excluir)
    y "keyword" (palabra que el texto debe mencionar) — son específicos de
    la marca que se está procesando en esta llamada, no de un default
    global. El mismo dominio puede ser oficial para una marca y no para
    otra (p.ej. www.latamairlines.com es oficial de LATAM, irrelevante
    para el filtro de Avianca).
    """
    if mention.get("platform") != "web":
        return True, ""

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
