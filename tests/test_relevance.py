from pipeline.relevance import is_relevant, is_spanish


def _web(text, author):
    return {"platform": "web", "text": text, "author": author}


TEXTO_ES = (
    "Volé con Avianca desde Bogotá y la verdad el servicio fue muy malo, "
    "perdieron mi maleta y nadie me dio una respuesta clara en el aeropuerto"
)


def test_pasa_mencion_web_legitima():
    ok, razon = is_relevant(_web(TEXTO_ES, "blogdeviajes.co"))
    assert ok is True
    assert razon == ""


def test_descarta_dominio_oficial():
    ok, razon = is_relevant(_web(TEXTO_ES, "www.avianca.com"))
    assert ok is False
    assert razon == "dominio_oficial"


def test_descarta_agregador_en_cualquier_tld():
    for dominio in ["rehlat.es", "au.rehlat.com", "www.rehlat.mx", "jo.rehlat.com"]:
        ok, razon = is_relevant(_web(TEXTO_ES, dominio))
        assert ok is False, dominio
        assert razon == "agregador", dominio


def test_descarta_metabuscador_con_subdominio_de_pais():
    # Caso real: vuelos.idealo.es pasaba antes de sumar "idealo" a la blacklist
    ok, razon = is_relevant(_web(TEXTO_ES, "vuelos.idealo.es"))
    assert ok is False
    assert razon == "agregador"


def test_descarta_tidal_y_jetcost():
    assert is_relevant(_web(TEXTO_ES, "tidal.com"))[1] == "agregador"
    assert is_relevant(_web(TEXTO_ES, "www.jetcost.pl"))[1] == "agregador"


def test_descarta_texto_en_otro_idioma():
    polaco = (
        "Daty podrozy w znaczacy sposob wplywaja na cene biletow lotniczych "
        "Jetcost pozwala wyszukac bilety lotnicze linii Avianca oraz innych "
        "przewoznikow dostepnych w naszej wyszukiwarce lotow online"
    )
    ok, razon = is_relevant(_web(polaco, "ejemplo.com"))
    assert ok is False
    assert razon == "idioma"


def test_descarta_texto_sin_la_palabra_avianca():
    texto = (
        "Los precios de los tiquetes aéreos para las vacaciones de fin de año "
        "subieron mucho este año según los datos que publicó el gremio del sector"
    )
    ok, razon = is_relevant(_web(texto, "ejemplo.com"))
    assert ok is False
    assert razon == "sin_keyword"


def test_texto_corto_no_se_filtra_por_idioma():
    # Menos de 15 palabras: demasiado corto para juzgar idioma
    assert is_spanish("Avianca perdió mi maleta otra vez") is True


def test_contenido_social_pasa_sin_evaluar():
    ok, razon = is_relevant({"platform": "instagram", "text": "ok", "author": "user1"})
    assert ok is True
    assert razon == ""
