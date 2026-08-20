import openpyxl
import pytest

from store import db, seed_excel

HEADERS = [
    "¿Queja real?", "Plataforma", "Texto", "Autor", "Fecha publicación",
    "URL", "Likes", "Shares", "Comentarios", "Sentiment +", "Sentiment -",
    "Sentiment =", "Emoción", "Extraído en",
]

TEXTO_ES = (
    "Volé con Avianca desde Bogotá y perdieron mi maleta, "
    "nadie me dio una respuesta clara en el aeropuerto para nada"
)


@pytest.fixture
def excel_v1(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    # web con fecha falsa (published_at == fetched_at)
    ws.append(["no", "web", TEXTO_ES, "blogdeviajes.co",
               "2026-06-05T20:31:34+00:00", "https://blog.co/1",
               0, 0, 0, 0, 0, 1, "neutral", "2026-06-05T20:31:34+00:00"])
    # web ruido de agregador
    ws.append(["no", "web", TEXTO_ES, "www.rehlat.es",
               "2026-06-05T20:31:34+00:00", "https://rehlat.es/1",
               0, 0, 0, 0, 0, 1, "neutral", "2026-06-05T20:31:34+00:00"])
    # tiktok con fecha real
    ws.append(["SÍ ⚠️", "tiktok", "Avianca me canceló el vuelo sin avisar", "user1",
               "2026-03-02T12:00:00+00:00", "https://tiktok.com/1",
               100, 5, 3, 0.1, 0.8, 0.1, "anger", "2026-06-05T20:31:34+00:00"])
    path = tmp_path / "v1.xlsx"
    wb.save(path)
    return str(path)


def test_read_excel_mapea_al_schema_v2(excel_v1):
    filas = seed_excel.read_excel(excel_v1)
    assert len(filas) == 3
    assert {f["platform"] for f in filas} == {"web", "tiktok"}
    assert all(f["classification_status"] == "unclassified" for f in filas)


def test_web_con_fecha_igual_a_fetched_at_queda_unknown(excel_v1):
    filas = seed_excel.read_excel(excel_v1)
    web = [f for f in filas if f["platform"] == "web"]
    assert all(f["date_confidence"] == "unknown" for f in web)
    assert all(f["published_at"] is None for f in web)


def test_tiktok_conserva_fecha_como_exact(excel_v1):
    filas = seed_excel.read_excel(excel_v1)
    tk = [f for f in filas if f["platform"] == "tiktok"][0]
    assert tk["date_confidence"] == "exact"
    assert tk["published_at"].startswith("2026-03-02")


def test_seed_descarta_ruido_y_cuenta_razones(excel_v1, tmp_db):
    res = seed_excel.seed(excel_v1, tmp_db)
    assert res["raw"] == 3
    assert res["filtered"] == 1
    assert res["filter_reasons"]["agregador"] == 1
    assert res["inserted"] == 2


def test_seed_dos_veces_no_duplica(excel_v1, tmp_db):
    seed_excel.seed(excel_v1, tmp_db)
    res = seed_excel.seed(excel_v1, tmp_db)
    assert res["inserted"] == 0
    assert res["duplicates"] == 2
    assert len(db.all_mentions(tmp_db)) == 2
