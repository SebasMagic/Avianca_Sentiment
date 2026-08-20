"""
Clasifica todas las menciones que están 'unclassified' en la DB, para una
sola marca.

Es idempotente y reanudable: lo que falló en una corrida sigue pendiente,
así que basta volver a llamarla para reintentarlo, sin re-scrapear nada.
"""
from pipeline.classifier import classify_texts
from store import db


def run(conn, brand: dict) -> dict:
    """
    `brand` es el perfil completo (config.get_brand(...)): se usa tanto
    para acotar qué pendientes tocar (brand["name"], vía
    db.pending_classification) como para construir el prompt correcto
    (el resto del perfil, vía classify_texts). Sin acotar por marca, una
    corrida de LATAM reclasificaría con el prompt de LATAM las menciones
    de Avianca que hubieran quedado pendientes de una corrida anterior.
    """
    pendientes = db.pending_classification(conn, brand=brand["name"])
    if not pendientes:
        print("[Classify] nada pendiente")
        return {"pendientes": 0, "clasificadas": 0, "fallidas": 0}

    print(f"[Classify] clasificando {len(pendientes)} menciones de {brand['name']}...")
    resultados = classify_texts([m["text"] for m in pendientes], brand)

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
