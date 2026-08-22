from config import get_brand
from pipeline.relevance import is_relevant, is_spanish

AVIANCA = get_brand("Avianca")
LATAM = get_brand("LATAM")


def _web(text, author):
    return {"platform": "web", "text": text, "author": author}


TEXTO_ES = (
    "Volé con Avianca desde Bogotá y la verdad el servicio fue muy malo, "
    "perdieron mi maleta y nadie me dio una respuesta clara en el aeropuerto"
)

# Menciona ambas marcas — usado para probar que el filtro de dominio oficial
# es específico de la marca que se pasa, no un default compartido.
TEXTO_AMBAS_MARCAS = TEXTO_ES + " y también volé con LATAM en código compartido"


def test_pasa_mencion_web_legitima():
    ok, razon = is_relevant(_web(TEXTO_ES, "blogdeviajes.co"), AVIANCA)
    assert ok is True
    assert razon == ""


def test_descarta_dominio_oficial():
    ok, razon = is_relevant(_web(TEXTO_ES, "www.avianca.com"), AVIANCA)
    assert ok is False
    assert razon == "dominio_oficial"


def test_dominio_oficial_es_especifico_por_marca():
    """El mismo dominio (www.latamairlines.com) debe descartarse al procesar
    LATAM pero no al procesar Avianca — is_relevant usa los dominios de la
    marca que se le pasa, no un default congelado al importar."""
    mention = _web(TEXTO_AMBAS_MARCAS, "www.latamairlines.com")

    ok_latam, razon_latam = is_relevant(mention, LATAM)
    assert (ok_latam, razon_latam) == (False, "dominio_oficial")

    # Mismo dominio, perfil de Avianca: no está en sus dominios oficiales,
    # y el texto sí menciona a Avianca — pasa.
    ok_avianca, razon_avianca = is_relevant(mention, AVIANCA)
    assert (ok_avianca, razon_avianca) == (True, "")


def test_descarta_agregador_en_cualquier_tld():
    for dominio in ["rehlat.es", "au.rehlat.com", "www.rehlat.mx", "jo.rehlat.com"]:
        ok, razon = is_relevant(_web(TEXTO_ES, dominio), AVIANCA)
        assert ok is False, dominio
        assert razon == "agregador", dominio


def test_descarta_metabuscador_con_subdominio_de_pais():
    # Caso real: vuelos.idealo.es pasaba antes de sumar "idealo" a la blacklist
    ok, razon = is_relevant(_web(TEXTO_ES, "vuelos.idealo.es"), AVIANCA)
    assert ok is False
    assert razon == "agregador"


def test_descarta_tidal_y_jetcost():
    assert is_relevant(_web(TEXTO_ES, "tidal.com"), AVIANCA)[1] == "agregador"
    assert is_relevant(_web(TEXTO_ES, "www.jetcost.pl"), AVIANCA)[1] == "agregador"


def test_descarta_texto_en_otro_idioma():
    polaco = (
        "Daty podrozy w znaczacy sposob wplywaja na cene biletow lotniczych "
        "Jetcost pozwala wyszukac bilety lotnicze linii Avianca oraz innych "
        "przewoznikow dostepnych w naszej wyszukiwarce lotow online"
    )
    ok, razon = is_relevant(_web(polaco, "ejemplo.com"), AVIANCA)
    assert ok is False
    assert razon == "idioma"


def test_descarta_texto_sin_la_palabra_avianca():
    texto = (
        "Los precios de los tiquetes aéreos para las vacaciones de fin de año "
        "subieron mucho este año según los datos que publicó el gremio del sector"
    )
    ok, razon = is_relevant(_web(texto, "ejemplo.com"), AVIANCA)
    assert ok is False
    assert razon == "sin_keyword"


def test_descarta_texto_sin_la_palabra_latam():
    texto = (
        "Los precios de los tiquetes aéreos para las vacaciones de fin de año "
        "subieron mucho este año según los datos que publicó el gremio del sector"
    )
    ok, razon = is_relevant(_web(texto, "ejemplo.com"), LATAM)
    assert ok is False
    assert razon == "sin_keyword"


def test_texto_corto_no_se_filtra_por_idioma():
    # Menos de 15 palabras: demasiado corto para juzgar idioma
    assert is_spanish("Avianca perdió mi maleta otra vez") is True


def test_contenido_social_pasa_sin_evaluar():
    # brand={} para dejar explícito que el perfil de marca ni se toca:
    # el short-circuit de contenido social ocurre antes de mirarlo.
    ok, razon = is_relevant({"platform": "instagram", "text": "ok", "author": "user1"}, {})
    assert ok is True
    assert razon == ""


# ── Filtro de hashtag (TikTok) — Tarea 1/2 de la corrección de relevancia
# social. Caso real que motivó esto: "#latam" trajo 29 videos, 28 eran
# ruido (memes de Latinoamérica, geografía, K-pop, sismos) y solo 1
# hablaba de la aerolínea (una reseña de vuelo en portugués). Un video de
# K-pop contenía literalmente "latam" en su descripción — un chequeo de
# keyword solo no alcanza, hace falta contexto aeronáutico.

def _tiktok(text, author=None):
    return {"platform": "tiktok", "text": text, "author": author}


def test_comentario_de_post_propio_no_pasa_por_el_filtro():
    """Instagram (comentarios de Fase 2 sobre el perfil oficial) nunca se
    evalúa — a diferencia de TikTok, que sí. Mismo texto (un meme sin
    relación con la aerolínea, sin keyword ni contexto aeronáutico): en
    Instagram pasa igual, en TikTok se descarta."""
    texto_meme = "Nieve en latam #viral #nieve #latam #humor"

    ok_ig, razon_ig = is_relevant({"platform": "instagram", "text": texto_meme, "author": "x"}, LATAM)
    assert (ok_ig, razon_ig) == (True, "")

    ok_tt, razon_tt = is_relevant(_tiktok(texto_meme), LATAM)
    assert ok_tt is False


def test_hashtag_descarta_meme_sin_contexto_aeronautico():
    """Caso real: video de K-pop bajo "#latam" con 224.700 de alcance —
    contiene "latam" en el texto sin hablar de la aerolínea."""
    texto = (
        "Usssshhhh es que nunca vienen a otro lugar que no sea Brasil,MEXICO,"
        "Argentina #latam #kpop #dahyun @TWICE"
    )
    ok, razon = is_relevant(_tiktok(texto), LATAM)
    assert ok is False
    assert razon == "sin_contexto_aeronautico"


def test_hashtag_conserva_resena_de_vuelo_en_portugues():
    """El único video relevante de los 29 de "#latam": una reseña de vuelo
    en portugués — "voando" es el término de contexto aeronáutico."""
    texto = (
        "Como foi minha experiência voando com a latam (Melhor que a Gol) "
        "na minha opinião #latam #latamairlines #miami #experiencia"
    )
    ok, razon = is_relevant(_tiktok(texto), LATAM)
    assert ok is True
    assert razon == ""


def test_hashtag_descarta_sin_keyword_de_marca():
    ok, razon = is_relevant(_tiktok("Un video cualquiera sin relación con la marca"), AVIANCA)
    assert ok is False
    assert razon == "sin_keyword"


def test_hashtag_requiere_keyword_y_contexto_a_la_vez():
    """Mencionar la marca no alcanza sin contexto aeronáutico (caso real:
    "Mi latam querida" — sobre Latinoamérica, no la aerolínea)."""
    ok, razon = is_relevant(_tiktok("Mi latam querida, la extraño mucho"), LATAM)
    assert ok is False
    assert razon == "sin_contexto_aeronautico"


def test_hashtag_pasa_con_contexto_aeronautico_en_ingles():
    ok, razon = is_relevant(
        _tiktok("Avianca flight attendant gets busted in Miami #colombia"), AVIANCA
    )
    assert ok is True
    assert razon == ""


def test_hashtag_pasa_con_contexto_aeronautico_sin_tilde():
    # "cancelacion" (sin tilde) debe contar igual que "cancelación".
    ok, razon = is_relevant(
        _tiktok("Avianca me acaba de avisar la cancelacion de mi vuelo"), AVIANCA
    )
    assert ok is True
    assert razon == ""


def test_hashtag_detecta_hashtag_compuesto_sin_espacio():
    """Caso real: hashtags de TikTok pegados sin espacio no producen un
    token igual a "airline" — "latamairlines" se reconoce por substring
    curado (ver AVIATION_CONTEXT_SUBSTRING_TERMS), no por palabra exacta."""
    ok, razon = is_relevant(
        _tiktok("Reliable and good quality! Only thing I'd improve is the food "
                "#LATAMairlines #airlinereview"),
        LATAM,
    )
    assert ok is True
    assert razon == ""


def test_hashtag_no_confunde_miles_con_smiles():
    """"miles" NUNCA se busca como substring (solo palabra completa) —
    "smiles" no debe activar el contexto aeronáutico."""
    ok, razon = is_relevant(_tiktok("Avianca siempre me saca smiles y buenas vibras"), AVIANCA)
    assert ok is False
    assert razon == "sin_contexto_aeronautico"


def test_hashtag_cuenta_oficial_pasa_sin_evaluar_contexto():
    """Un video publicado por la cuenta oficial de la marca es relevante
    aunque el texto no tenga ninguna palabra de contexto aeronáutico —
    el mismo argumento que exime a los comentarios de Instagram."""
    ok, razon = is_relevant(
        _tiktok("Feliz viernes a todos ✈️💙", author="latam_colombia"), LATAM
    )
    assert ok is True
    assert razon == ""


def test_hashtag_cuenta_oficial_es_especifica_por_marca():
    """"latam_colombia" es oficial de LATAM, no de Avianca — el mismo
    autor con el perfil de Avianca sí se evalúa normalmente."""
    ok, razon = is_relevant(
        _tiktok("Feliz viernes a todos", author="latam_colombia"), AVIANCA
    )
    assert ok is False
    assert razon == "sin_keyword"


def test_hashtag_cuenta_no_oficial_con_nombre_parecido_si_se_evalua():
    """"avianca_b" no es la cuenta oficial (nombre distinto, con sufijo) —
    debe evaluarse por keyword/contexto como cualquier otra cuenta."""
    ok, razon = is_relevant(
        _tiktok("Holding it down this summer", author="avianca_b"), AVIANCA
    )
    assert ok is False
    assert razon == "sin_keyword"


# ── prensa (Google News, scrapers/dataforseo_news.py) ──────────────────
#
# Misma estructura de dos ramas que el filtro de hashtag: dominio de
# medio reconocido, o keyword + contexto aeronáutico. Casos calibrados
# contra datos reales de la API (2026-08-21/22, ver
# config.RECOGNIZED_MEDIA_DOMAINS y .superpowers/prensa-resenas.md).

def _prensa(text, author=None):
    return {"platform": "prensa", "text": text, "author": author}


def test_prensa_pasa_con_keyword_y_contexto_aeronautico():
    ok, razon = is_relevant(
        _prensa("Avianca anuncia el desenlace de la polémica con Yeferson Cossio: "
                "el influencer no podrá volar con la aerolínea durante un año",
                author="unmedio-no-listado.co"),
        AVIANCA,
    )
    assert ok is True
    assert razon == ""


def test_prensa_descarta_mencion_de_pasada_sin_contexto_ni_medio_reconocido():
    """Caso real: la keyword "LATAM" también es la abreviatura de
    Latinoamérica — una nota sobre porcicultura o sobre un sindicato que
    de pura casualidad usa "Latam" en el texto no es cobertura de la
    aerolínea."""
    ok, razon = is_relevant(
        _prensa("El sindicato Latam rechaza la derogación de once circulares "
                "laborales en Colombia", author="latamgremial.com"),
        LATAM,
    )
    assert ok is False
    assert razon == "sin_contexto_aeronautico"


def test_prensa_descarta_nota_sin_la_keyword_en_absoluto():
    ok, razon = is_relevant(
        _prensa("El aeropuerto El Dorado bate récord de pasajeros este semestre",
                author="unmedio-no-listado.co"),
        AVIANCA,
    )
    assert ok is False
    assert razon == "sin_keyword"


def test_prensa_medio_reconocido_pasa_sin_exigir_contexto_aeronautico():
    """Caso real: Blu Radio publicó "LATAM transporta gratis 36 toneladas
    de ayuda al Chocó" — genuinamente sobre la aerolínea, pero sin
    ninguna palabra de AVIATION_CONTEXT_WORDS en el título."""
    ok, razon = is_relevant(
        _prensa("LATAM transporta gratis 36 toneladas de ayuda al Chocó; "
                "ya suma 119 toneladas por el terremoto", author="www.bluradio.com"),
        LATAM,
    )
    assert ok is True
    assert razon == ""


def test_prensa_medio_reconocido_es_por_etiqueta_de_dominio():
    """"www.eltiempo.com" y "eltiempo.com" deben reconocerse igual — el
    match es por etiqueta, como _is_blacklisted."""
    for dominio in ["www.eltiempo.com", "eltiempo.com", "amp.eltiempo.com"]:
        ok, razon = is_relevant(_prensa("cualquier titular sin contexto", author=dominio), AVIANCA)
        assert ok is True, dominio
        assert razon == "", dominio


def test_prensa_medio_no_reconocido_si_se_evalua_por_contexto():
    """Caso real: forbes.co trajo una nota sobre IA antifraude sin ninguna
    relación con la aerolínea al buscar "LATAM" — forbes.co NO está en
    RECOGNIZED_MEDIA_DOMAINS a propósito, así que cae a la rama de
    keyword + contexto y se descarta."""
    ok, razon = is_relevant(
        _prensa("Del tribunal a la primera IA antifraude certificada en Latam",
                author="forbes.co"),
        LATAM,
    )
    assert ok is False


def test_prensa_avianca_no_ambiguo_pasa_con_solo_keyword_y_contexto():
    """Para "Avianca" (nombre propio sin ambigüedad, a diferencia de
    "LATAM") la keyword + contexto alcanza sin necesidad de whitelist."""
    ok, razon = is_relevant(
        _prensa("Yeferson Cossio no viajará en Avianca hasta 2027: así se resolvió "
                "la polémica del influencer con la aerolínea",
                author="undiariolocal.com"),
        AVIANCA,
    )
    assert ok is True
    assert razon == ""
