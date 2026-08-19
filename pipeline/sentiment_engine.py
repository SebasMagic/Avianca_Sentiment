"""
Sentiment engine usando DeepSeek API (compatible con OpenAI).
- Plataforma "web": sentiment ya viene de DataForSEO, no hace nada.
- Plataformas "instagram", "tiktok", "twitter": usa DeepSeek para clasificar.
Procesa en batches de 10 para minimizar llamadas a la API.
"""
import json
import requests
from config import DEEPSEEK_API_KEY

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """Eres un analizador de sentiment especializado en menciones de marca en español latinoamericano.
Dado un texto, retorna ÚNICAMENTE un JSON con este formato exacto, sin explicaciones adicionales:
{
  "sentiment_positive": 0.0,
  "sentiment_negative": 0.0,
  "sentiment_neutral": 1.0,
  "emotion": "happiness",
  "is_complaint": false
}
Reglas:
- Los tres valores de sentiment deben sumar 1.0
- emotion debe ser exactamente uno de: "happiness", "anger", "love", "sadness", "neutral"
- is_complaint es true SOLO si el texto es una queja real de un usuario sobre el servicio (vuelos cancelados, maletas perdidas, mal servicio, cobros indebidos, demoras, atención al cliente, etc.)
- is_complaint es false si es contenido promocional, noticias, opinión neutral, o contenido positivo
- Contexto: el texto es un comentario o mención sobre la aerolínea Avianca en Colombia
- Sé preciso con el español coloquial colombiano"""


def _analyze_batch(texts: list[str]) -> list[dict]:
    prompt = f"""Analiza el sentiment de cada uno de los siguientes {len(texts)} textos sobre Avianca.
Retorna un array JSON con exactamente {len(texts)} objetos en el mismo orden.
No incluyas texto antes o después del JSON.

Textos:
{json.dumps(texts, ensure_ascii=False, indent=2)}

Responde SOLO con el array JSON:"""

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
                {"role": "user",   "content": prompt},
            ],
            "max_tokens": 1000,
            "temperature": 0.1,
        },
        timeout=30,
    )
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


def enrich_sentiment(mentions: list[dict]) -> list[dict]:
    """
    Enriquece menciones de redes sociales con sentiment de DeepSeek.
    Las menciones web ya tienen sentiment de DataForSEO y se pasan sin cambios.
    """
    web_mentions    = [m for m in mentions if m["platform"] == "web"]
    social_mentions = [m for m in mentions if m["platform"] != "web"]

    if not social_mentions:
        return mentions

    print(f"[Sentiment] Analizando {len(social_mentions)} menciones con DeepSeek...")

    batch_size = 10
    enriched = []

    for i in range(0, len(social_mentions), batch_size):
        batch = social_mentions[i:i + batch_size]
        texts = [m["text"] for m in batch]

        try:
            sentiments = _analyze_batch(texts)
            for mention, sentiment in zip(batch, sentiments):
                mention.update({
                    "sentiment_positive": float(sentiment.get("sentiment_positive", 0.0)),
                    "sentiment_negative": float(sentiment.get("sentiment_negative", 0.0)),
                    "sentiment_neutral":  float(sentiment.get("sentiment_neutral",  1.0)),
                    "emotion":      sentiment.get("emotion", "neutral"),
                    "is_complaint": bool(sentiment.get("is_complaint", False)),
                })
                enriched.append(mention)
        except Exception as e:
            print(f"[Sentiment] Error en batch {i//batch_size + 1}: {e}")
            enriched.extend(batch)

    print(f"[Sentiment] Completado: {len(enriched)} menciones enriquecidas")
    return web_mentions + enriched
