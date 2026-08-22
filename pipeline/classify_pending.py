"""
Clasifica todas las menciones que están 'unclassified' en la DB, para una
sola marca — SIN distinguir plataforma. db.pending_classification()
devuelve instagram, tiktok, resena Y prensa por igual, y las cuatro pasan
por el mismo prompt de pipeline/classifier.py (Tarea 3 de prensa/
reseñas: "ambas fuentes pasan por el clasificador con los mismos
drivers" — una nota de prensa sobre una demanda cae en "cancelacion" o
"equipaje" con el mismo vocabulario que una queja social).

La distinción entre "cobertura de prensa" y "queja de un usuario" NO vive
acá — sería el lugar equivocado, porque el clasificador no sabe ni le
importa de qué plataforma vino el texto. Vive en dashboard/aggregate.py:
platform="prensa" se separa del resto antes de calcular la tasa de
quejas del KPI principal, y se agrega por su cuenta en payload["press"]
(mismo is_complaint/complaint_driver, leído con otro propósito: "temas de
la cobertura", no "quejas de servicio"). Ver el docstring de ese módulo.

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

    clasificadas = 0
    fallidas = 0

    # Se persiste por tramos, no al final. Antes se llamaba al LLM para TODAS
    # las pendientes y recién después se escribía: con miles de menciones eso
    # son decenas de minutos en los que cualquier interrupción perdía el
    # trabajo completo — y el dinero ya gastado en esas llamadas. Escribir
    # cada tramo hace la corrida reanudable: lo ya clasificado queda firme y
    # al volver a correr solo se piden las que siguen pendientes.
    TRAMO = 100

    for inicio in range(0, len(pendientes), TRAMO):
        tramo = pendientes[inicio:inicio + TRAMO]
        resultados = classify_texts([m["text"] for m in tramo], brand)

        for mention, resultado in zip(tramo, resultados):
            if resultado is None:
                fallidas += 1
                continue
            db.update_classification(conn, mention["id"], resultado)
            clasificadas += 1

        print(f"[Classify] {clasificadas}/{len(pendientes)} clasificadas"
              f" ({fallidas} fallidas)", flush=True)
    return {
        "pendientes": len(pendientes),
        "clasificadas": clasificadas,
        "fallidas": fallidas,
    }
