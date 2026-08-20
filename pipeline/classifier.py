"""
Clasificador de menciones. Único módulo que habla con DeepSeek.

Un solo llamado devuelve sentiment, emoción, si es queja y el driver
operativo — el driver sale gratis, va en el mismo prompt.

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

SYSTEM_PROMPT = f"""Eres un analizador de menciones de marca en español latinoamericano, especializado en la aerolínea Avianca en Colombia.

Para cada texto retorna ÚNICAMENTE un JSON con este formato exacto:
{{
  "sentiment_positive": 0.0,
  "sentiment_negative": 0.0,
  "sentiment_neutral": 1.0,
  "emotion": "happiness",
  "is_complaint": false,
  "complaint_driver": null
}}

Reglas:
- Los tres valores de sentiment deben sumar 1.0
- emotion es exactamente uno de: "happiness", "anger", "love", "sadness", "neutral"
- is_complaint es true SOLO si es una queja real de un usuario sobre el servicio.
  Es false para contenido promocional, noticias, opinión neutral o contenido positivo.
- complaint_driver es null cuando is_complaint es false.
  Cuando is_complaint es true, es OBLIGATORIO y debe ser exactamente uno de:
    "equipaje"          — maletas perdidas, dañadas o demoradas (manejo físico del equipaje)
    "cancelacion"       — vuelos cancelados, reprogramados sin aviso
    "demora"            — retrasos, conexiones perdidas por retraso
    "atencion_cliente"  — mal trato, call center, falta de respuesta, personal
    "cobros_tarifas"    — cobros indebidos, precios, cargos ocultos, penalidades, cobros de equipaje
    "lifemiles"         — millas, programa de fidelidad, redenciones
    "asientos_comida"   — asientos, espacio, comida a bordo, entretenimiento
    "reembolsos"        — devoluciones de dinero que no llegan o se demoran
    "otro"              — queja real que no encaja en ninguna de las anteriores
- Ante duda sobre la categoría de una queja real, usa "otro".
- Muchas quejas encajan literalmente en más de un driver a la vez (la maleta
  no llegó porque cancelaron el vuelo; cobraron de más y nunca devolvieron
  el dinero; "cobros de equipaje" suena a la vez a equipaje y a tarifas).
  Para esos casos, elige el PRIMERO que aplique en este orden de precedencia,
  no el que te parezca más específico:
    cancelacion > demora > equipaje > reembolsos > cobros_tarifas
    > lifemiles > asientos_comida > atencion_cliente > otro
  Esta prioridad no es arbitraria:
  (a) las disrupciones de vuelo (cancelacion, demora) van primero porque son
      la causa raíz accionable — si la maleta no llegó porque cancelaron el
      vuelo, lo que hay que arreglar es la cancelación, no el equipaje;
  (b) atencion_cliente va casi al final a propósito, porque casi toda queja
      incluye "y nadie me ayudó" — si fuera prioritario se tragaría el resto
      de las categorías y perderíamos la causa real del problema.
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

    return {
        "sentiment_positive": round(pos, 4),
        "sentiment_negative": round(neg, 4),
        "sentiment_neutral": round(neu, 4),
        "emotion": emotion,
        "is_complaint": is_complaint,
        "complaint_driver": driver,
    }


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _call_api(texts: list[str]) -> list[dict | None]:
    """
    Un llamado a DeepSeek. Lanza si la respuesta no es una lista del
    mismo largo que la entrada — nunca hace zip a ciegas.

    Un elemento individual que no sea un objeto clasificable (null,
    string, número) se convierte en None vía normalize_result, no en
    un neutral — la longitud del batch puede ser correcta y aun así
    contener ítems que el modelo no logró estructurar.
    """
    prompt = (
        f"Analiza cada uno de los siguientes {len(texts)} textos sobre Avianca.\n"
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
                {"role": "system", "content": SYSTEM_PROMPT},
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


def _attempt(texts: list[str]) -> list[dict | None] | None:
    """
    Intenta un batch con reintentos. Devuelve None (todo el intento) si
    nunca funcionó; si funcionó, devuelve una lista del mismo largo que
    `texts`, que puede a su vez contener None por ítem individual sin
    estructurar (ver _call_api).
    """
    for intento in range(MAX_RETRIES + 1):
        try:
            return _call_api(texts)
        except Exception as e:
            print(f"[Classifier] intento {intento + 1} falló: {e}")
            if intento < MAX_RETRIES:
                time.sleep(2 ** intento)
    return None


def classify_texts(texts: list[str]) -> list[dict | None]:
    """
    Clasifica una lista de textos. Devuelve una lista del mismo largo:
    un dict por texto clasificado, o None por texto que no se pudo clasificar.

    Estrategia: batch completo → reintentos → item por item.
    """
    if not texts:
        return []

    results: list[dict | None] = []

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]

        batch_result = _attempt(batch)
        if batch_result is not None:
            results.extend(batch_result)
            continue

        # El batch no salió ni con reintentos: uno por uno.
        print(f"[Classifier] batch de {len(batch)} falló; cayendo a item por item")
        for text in batch:
            single = _attempt([text])
            results.append(single[0] if single else None)

    return results
