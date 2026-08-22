"""
Clasificador de menciones. Único módulo que habla con DeepSeek.

Un solo llamado devuelve sentiment, emoción, si es queja y el driver
operativo — el driver sale gratis, va en el mismo prompt. También devuelve
is_service_conversation: si el texto habla del SERVICIO de la aerolínea
(volar, atención, equipaje, precios) o solo reacciona a una publicación o
campaña de marketing sin decir nada del servicio (ver build_system_prompt
y el docstring de dashboard/aggregate.py, kpis.complaint_rate_service) —
el campo que separa "conversación de servicio" de "ruido de campaña" en el
denominador de la tasa de queja.

Diferencias clave con el sentiment_engine del v1:
  - TODAS las plataformas pasan por aquí, incluida 'web'. DataForSEO
    devolvió connotation_types vacío, así que sus menciones nunca se
    analizaron.
  - Si la respuesta no tiene la misma longitud que el batch, NO se hace
    zip (eso truncaba en silencio). Se reintenta y luego se cae a
    item por item.
  - Lo que no se logra clasificar devuelve None, no un neutral falso.
    Esto incluye el caso ítem por ítem: si el array JSON tiene la
    longitud correcta pero un elemento puntual no es un objeto (el LLM
    a veces devuelve null para un ítem que no logró estructurar),
    normalize_result devuelve None para ESE elemento en vez de colarlo
    como neutral. No existe ningún camino en este módulo que produzca
    un neutral sintético.
"""
import json
import time

import requests

from config import COMPLAINT_DRIVERS, DEEPSEEK_API_KEY

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

BATCH_SIZE = 10
MAX_RETRIES = 1

VALID_EMOTIONS = {"happiness", "anger", "love", "sadness", "neutral"}


def build_system_prompt(brand: dict) -> str:
    """
    Arma el system prompt de DeepSeek con la marca y su programa de
    fidelidad inyectados desde el perfil (config.BRANDS) — antes decía
    "Avianca" y describía el driver "lifemiles" a secas, fijos en el
    código. Con dos marcas en la misma base, un prompt fijo hacía que el
    modelo analizara menciones de LATAM como si fueran de Avianca.
    """
    keyword = brand["keyword"]
    loyalty_program = brand["loyalty_program"]
    return f"""Eres un analizador de menciones de marca en español latinoamericano, especializado en la aerolínea {keyword} en Colombia.

Para cada texto retorna ÚNICAMENTE un JSON con este formato exacto:
{{
  "sentiment_positive": 0.0,
  "sentiment_negative": 0.0,
  "sentiment_neutral": 1.0,
  "emotion": "happiness",
  "is_service_conversation": true,
  "is_complaint": false,
  "complaint_driver": null
}}

Reglas:
- Los tres valores de sentiment deben sumar 1.0
- emotion es exactamente uno de: "happiness", "anger", "love", "sadness", "neutral"
- is_service_conversation distingue si el texto habla del SERVICIO de {keyword}
  (volar con la aerolínea, atención recibida, equipaje, precios/tarifas, la
  marca como proveedor de un vuelo, o una consulta práctica sobre volar con
  ella) de si solo REACCIONA a una publicación o campaña de marketing sin decir
  nada sobre el servicio mismo (celebrar un video, un gol, etiquetar a un
  amigo, elogiar la pieza publicitaria, ánimo genérico de una campaña como un
  mundial de fútbol: banderas, "vamos con todo", "qué lindo contenido").
    true  -> el texto opina, describe o pregunta algo sobre EL SERVICIO,
             aunque sea en una sola palabra o sea muy positivo. Ejemplos:
             "La mejor aerolínea en mi opinión" (opinión de servicio, aunque
             sea positiva); "Para viajar a EEUU necesito visa?" (consulta
             práctica sobre volar con la marca, no una reacción a contenido).
    false -> el texto reacciona al POST/CAMPAÑA, no al servicio. Ejemplos:
             "Genial este contenido!"; "Modo mundial activado"; etiquetar a
             un amigo sin más comentario; emojis de bandera o de celebración
             sin mencionar volar, atención, equipaje o precio.
  Toda queja (is_complaint=true) es SIEMPRE is_service_conversation=true —
  no existe una queja real de servicio que no sea, por definición,
  conversación de servicio.
- is_complaint es true SOLO si es una queja real de un usuario sobre el servicio.
  Es false para contenido promocional, noticias, opinión neutral o contenido positivo.
  También es false para peticiones o sugerencias sin queja de servicio de por
  medio — p. ej. pedir que abran una ruta nueva, o pedir que la aerolínea
  done vuelos para una causa humanitaria. Eso es una petición, no una queja
  sobre el servicio que el usuario recibió.
- complaint_driver es null cuando is_complaint es false.
  Cuando is_complaint es true, es OBLIGATORIO y debe ser exactamente uno de:
    "equipaje"           — maletas perdidas, dañadas o demoradas (manejo físico del equipaje)
    "cancelacion"        — vuelos cancelados, reprogramados sin aviso
    "demora"             — retrasos, conexiones perdidas por retraso
    "atencion_cliente"   — mal trato, call center, falta de respuesta, personal
    "cobros_tarifas"     — cobros indebidos, precios, cargos ocultos, penalidades, cobros de equipaje
    "programa_fidelidad" — millas, programa de fidelidad ({loyalty_program}), redenciones
    "asientos_comida"    — asientos, espacio, comida a bordo, entretenimiento
    "reembolsos"         — devoluciones de dinero que no llegan o se demoran
    "mascotas"           — mascotas o animales que viajan con el pasajero: pérdida,
                            maltrato, muerte, o problemas con la política de transporte
                            de mascotas (bodega o cabina)
    "fraude_publicidad"  — páginas, perfiles o anuncios FALSOS que suplantan la marca
                            para estafar, o publicidad/promociones de la propia
                            aerolínea que el usuario considera engañosas. No es esto
                            un cobro ya hecho de más (eso es "cobros_tarifas") — es
                            sobre la promesa o la suplantación, no sobre el cobro.
    "rechazo_marca"      — rechazo o insulto genérico hacia la marca SIN mencionar
                            ninguna causa operativa concreta (no aplica ningún driver
                            anterior). Úsalo en vez de "otro" cuando la queja es pura
                            negatividad o insulto sin motivo específico — "son lo
                            peor", "delincuentes", "#noavianca" sin más contexto.
    "otro"                — queja real que no encaja en NINGUNA de las anteriores,
                            ni siquiera "rechazo_marca" — reservado para lo que de
                            verdad no tiene categoría (p. ej. amenazas legales,
                            fallas puntuales de la app, problemas técnicos del avión).
- Ante duda entre "otro" y cualquier otra categoría de esta lista (incluida
  "rechazo_marca"), prefiere la categoría de esta lista — "otro" es el
  último recurso, no la opción por defecto.
- Muchas quejas encajan literalmente en más de un driver a la vez (la maleta
  no llegó porque cancelaron el vuelo; cobraron de más y nunca devolvieron
  el dinero; "cobros de equipaje" suena a la vez a equipaje y a tarifas).
  Para esos casos, elige el PRIMERO que aplique en este orden de precedencia,
  no el que te parezca más específico:
    cancelacion > demora > equipaje > mascotas > reembolsos > cobros_tarifas
    > fraude_publicidad > programa_fidelidad > asientos_comida
    > atencion_cliente > rechazo_marca > otro
  Esta prioridad no es arbitraria:
  (a) las disrupciones de vuelo (cancelacion, demora) van primero porque son
      la causa raíz accionable — si la maleta no llegó porque cancelaron el
      vuelo, lo que hay que arreglar es la cancelación, no el equipaje;
  (b) "mascotas" va justo después de "equipaje" por la misma lógica: si el
      motivo de fondo es el manejo físico de lo que el pasajero llevaba
      consigo —maleta o mascota—, gana la causa concreta sobre cualquier
      categoría genérica;
  (c) "fraude_publicidad" va junto a las categorías de dinero (después de
      "cobros_tarifas") porque comparte el mismo terreno — promesas y
      confianza sobre precios y ofertas — pero es una causa distinta de un
      cobro ya hecho, así que tiene su propio lugar en vez de perderse
      dentro de "cobros_tarifas";
  (d) atencion_cliente va casi al final a propósito, porque casi toda queja
      incluye "y nadie me ayudó" — si fuera prioritario se tragaría el resto
      de las categorías y perderíamos la causa real del problema;
  (e) "rechazo_marca" va al final, justo antes de "otro", porque es la
      categoría MÁS genérica de todas — solo aplica cuando NINGUNA causa
      operativa concreta está presente. Si hay aunque sea un indicio de
      causa concreta (equipaje, demora, cobro, etc.), esa causa gana sobre
      "rechazo_marca", igual que gana sobre "otro".
- Sé preciso con el español coloquial colombiano."""


def _clamp(value, default=0.0):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value) -> bool:
    """bool() normal, salvo por strings tipo 'false'/'no'/'0' que no deben
    contar como verdaderos (algunos LLM devuelven booleanos como texto)."""
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "0", "")
    return bool(value)


def normalize_result(raw: dict) -> dict | None:
    """
    Sanea la respuesta del modelo al contrato. Nunca lanza.

    Devuelve None (no un neutral sintético) cuando `raw` no es un dict
    clasificable — p. ej. el LLM devolvió null, un string o un número
    para ese ítem puntual dentro de un array por lo demás válido. Un
    None aquí se propaga tal cual hasta classify_texts, para que quien
    llame lo trate como "no clasificado", nunca como "neutral real".
    """
    if not isinstance(raw, dict):
        return None

    pos = _clamp(raw.get("sentiment_positive"))
    neg = _clamp(raw.get("sentiment_negative"))
    neu = _clamp(raw.get("sentiment_neutral"))
    total = pos + neg + neu
    if total <= 0:
        pos, neg, neu = 0.0, 0.0, 1.0
    elif abs(total - 1.0) > 0.05:
        pos, neg, neu = pos / total, neg / total, neu / total

    emotion = raw.get("emotion")
    if not isinstance(emotion, str) or emotion not in VALID_EMOTIONS:
        emotion = "neutral"

    is_complaint = _to_bool(raw.get("is_complaint", False))

    driver = raw.get("complaint_driver")
    if not is_complaint:
        driver = None
    elif driver not in COMPLAINT_DRIVERS:
        driver = "otro"

    # Toda queja es, por definición, conversación de servicio (ver el
    # prompt más arriba) — se fuerza acá, no solo se le pide al modelo, para
    # que una inconsistencia puntual del LLM (marcar una queja real como
    # "reacción a campaña") nunca contamine el denominador de
    # kpis.complaint_rate_service (dashboard/aggregate.py): una queja jamás
    # puede quedar fuera de la conversación de servicio que ella misma prueba
    # que existe.
    is_service_conversation = is_complaint or _to_bool(raw.get("is_service_conversation", False))

    return {
        "sentiment_positive": round(pos, 4),
        "sentiment_negative": round(neg, 4),
        "sentiment_neutral": round(neu, 4),
        "emotion": emotion,
        "is_complaint": is_complaint,
        "complaint_driver": driver,
        "is_service_conversation": is_service_conversation,
    }


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _call_api(texts: list[str], brand: dict) -> list[dict | None]:
    """
    Un llamado a DeepSeek. Lanza si la respuesta no es una lista del
    mismo largo que la entrada — nunca hace zip a ciegas.

    Un elemento individual que no sea un objeto clasificable (null,
    string, número) se convierte en None vía normalize_result, no en
    un neutral — la longitud del batch puede ser correcta y aun así
    contener ítems que el modelo no logró estructurar.
    """
    prompt = (
        f"Analiza cada uno de los siguientes {len(texts)} textos sobre {brand['keyword']}.\n"
        f"Retorna un array JSON con exactamente {len(texts)} objetos, en el mismo orden.\n"
        "No incluyas texto antes ni después del JSON.\n\n"
        f"Textos:\n{json.dumps(texts, ensure_ascii=False, indent=2)}\n\n"
        "Responde SOLO con el array JSON:"
    )

    response = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": build_system_prompt(brand)},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        },
        timeout=60,
    )
    response.raise_for_status()

    content = _strip_fences(response.json()["choices"][0]["message"]["content"])
    parsed = json.loads(content)

    if not isinstance(parsed, list):
        raise ValueError("la respuesta no es un array")
    if len(parsed) != len(texts):
        raise ValueError(
            f"longitud desigual: se pidieron {len(texts)}, llegaron {len(parsed)}"
        )

    return [normalize_result(p) for p in parsed]


def _attempt(texts: list[str], brand: dict) -> list[dict | None] | None:
    """
    Intenta un batch con reintentos. Devuelve None (todo el intento) si
    nunca funcionó; si funcionó, devuelve una lista del mismo largo que
    `texts`, que puede a su vez contener None por ítem individual sin
    estructurar (ver _call_api).
    """
    for intento in range(MAX_RETRIES + 1):
        try:
            return _call_api(texts, brand)
        except Exception as e:
            print(f"[Classifier] intento {intento + 1} falló: {e}")
            if intento < MAX_RETRIES:
                time.sleep(2 ** intento)
    return None


def classify_texts(texts: list[str], brand: dict) -> list[dict | None]:
    """
    Clasifica una lista de textos sobre `brand`. Devuelve una lista del
    mismo largo: un dict por texto clasificado, o None por texto que no
    se pudo clasificar.

    Estrategia: batch completo → reintentos → item por item.
    """
    if not texts:
        return []

    results: list[dict | None] = []

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]

        batch_result = _attempt(batch, brand)
        if batch_result is not None:
            results.extend(batch_result)
            continue

        # El batch no salió ni con reintentos: uno por uno.
        print(f"[Classifier] batch de {len(batch)} falló; cayendo a item por item")
        for text in batch:
            single = _attempt([text], brand)
            results.append(single[0] if single else None)

    return results
