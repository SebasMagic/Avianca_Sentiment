"""
Supabase writer.
Inserta menciones normalizadas en la tabla brand_mentions.
Usa upsert para evitar duplicados por source_url + platform.
"""
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def write_mentions(mentions: list[dict]) -> int:
    if supabase is None:
        print("[Supabase] Sin credenciales — saltando escritura en DB")
        return 0
    """
    Inserta menciones en Supabase.
    Retorna cantidad de filas insertadas.
    """
    if not mentions:
        return 0

    rows = []
    for m in mentions:
        row = {k: v for k, v in m.items() if k != "raw"}
        row["raw"] = m.get("raw", {})
        rows.append(row)

    response = (
        supabase.table("brand_mentions")
        .upsert(rows, on_conflict="platform,source_url")
        .execute()
    )

    count = len(response.data) if response.data else 0
    print(f"[Supabase] {count} menciones guardadas")
    return count


def get_summary() -> dict:
    """Retorna resumen de menciones guardadas para logging."""
    if supabase is None:
        return {"total": 0}
    result = supabase.table("brand_mentions").select("platform", count="exact").execute()
    return {"total": result.count}
