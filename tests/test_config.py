"""
Test de regresión: handles de Instagram de LATAM.

Bug real encontrado en el backfill de LATAM (2026-08-20): config.BRANDS
tenía "latam_airlines" y "latamcolombia" como perfiles de Instagram.
Ninguno de los dos existe — el actor de Apify los devuelve como
{"error": "not_found"} en la Fase 1 (verificado contra la API real), así
que apify_instagram.scrape() caía en "Sin posts para extraer comentarios"
sin ningún error visible: 0 menciones de Instagram, corrida "exitosa".

Los handles reales (verificados vía Instagram el 2026-08-20, ambos con
cuenta verificada y posts recientes) son @latamairlines (global) y
@latamairlines_colombia (Colombia). Este test fija esos valores para que
un futuro cambio accidental de config no repita el mismo fallo silencioso.
"""
from config import get_brand

LATAM = get_brand("LATAM")


def test_perfiles_instagram_latam_son_los_handles_reales():
    assert LATAM["instagram_profiles"] == [
        "https://www.instagram.com/latamairlines/",
        "https://www.instagram.com/latamairlines_colombia/",
    ]
