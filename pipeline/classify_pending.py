"""
Clasifica todas las menciones que están 'unclassified' en la DB.

Es idempotente y reanudable: lo que falló en una corrida sigue pendiente,
así que basta volver a llamarla para reintentarlo, sin re-scrapear nada.
"""
from pipeline.classifier import classify_texts
from store import db


def run(conn) -> dict:
    pendientes = db.pending_classification(conn)
    if not pendientes:
        print("[Classify] nada pendiente")
        return {"pendientes": 0, "clasificadas": 0, "fallidas": 0}

    print(f"[Classify] clasificando {len(pendientes)} menciones...")
    resultados = classify_texts([m["text"] for m in pendientes])

    clasificadas = 0
    fallidas = 0

    for mention, resultado in zip(pendientes, resultados):
        if resultado is None:
            fallidas += 1
            continue
        db.update_classification(conn, mention["id"], resultado)
        clasificadas += 1

    print(f"[Classify] {clasificadas} clasificadas, {fallidas} fallidas")
    return {
        "pendientes": len(pendientes),
        "clasificadas": clasificadas,
        "fallidas": fallidas,
    }
