import sqlite3

from config import DEFAULT_BRAND
from store import db


def _mention(text="Avianca me perdió la maleta en Bogotá",
             url="https://x.com/1", mid="m-1",
             fetched_at="2026-08-19T00:00:00+00:00",
             author="usuario1", published_at="2026-05-01T10:00:00+00:00",
             brand=None):
    m = {
        "id": mid,
        "platform": "tiktok",
        "source_url": url,
        "text": text,
        "author": author,
        "published_at": published_at,
        "date_confidence": "exact",
        "country": "CO",
        "likes": 10,
        "shares": 2,
        "comments_count": 3,
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.0,
        "sentiment_neutral": 1.0,
        "emotion": "neutral",
        "is_complaint": 0,
        "complaint_driver": None,
        "classification_status": "unclassified",
        "raw": {"foo": "bar"},
        "fetched_at": fetched_at,
    }
    if brand is not None:
        m["brand"] = brand
    return m


def test_fingerprint_es_estable_y_ignora_id():
    a = db.fingerprint("Avianca", "tiktok", "https://x.com/1", "user1", "hola mundo")
    b = db.fingerprint("Avianca", "tiktok", "https://x.com/1", "user1", "hola mundo")
    assert a == b
    assert len(a) == 64


def test_fingerprint_distingue_texto_distinto_en_misma_url():
    a = db.fingerprint("Avianca", "tiktok", "https://x.com/1", "user1", "hola mundo")
    b = db.fingerprint("Avianca", "tiktok", "https://x.com/1", "user1", "otro comentario distinto")
    assert a != b


def test_fingerprint_distingue_marcas_distintas_mismo_contenido():
    """Dos marcas pueden compartir una mención legítimamente idéntica (p.ej.
    una nota de prensa que nombra a ambas) — no deben fusionarse en el dedup."""
    a = db.fingerprint("Avianca", "web", "https://noticias.co/1", "noticias.co", "anuncio conjunto")
    b = db.fingerprint("LATAM", "web", "https://noticias.co/1", "noticias.co", "anuncio conjunto")
    assert a != b


def test_dos_marcas_con_texto_identico_no_se_deduplican_entre_si(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(mid="m-1", brand="Avianca"),
            _mention(mid="m-2", brand="LATAM"),
        ],
        run_id,
    )
    assert (ins, dup) == (2, 0)
    assert len(db.all_mentions(tmp_db)) == 2


def test_fingerprint_distingue_autores_distintos_en_misma_url_mismo_texto(tmp_db):
    """Regresión: Instagram scrape usa URL genérica para todos los comentarios.
    Si dos usuarios distintos escriben lo mismo en esa URL, SON dos menciones
    diferentes, no un duplicado. El fingerprint debe incluir author para evitar
    falsos positivos.

    Caso real: catherine_zik_oppenheimer y valentina_ahumada977 comentaron
    '❤️❤️❤️❤️❤️' en fechas distintas (2026-06-02 vs 2026-05-29) en
    https://www.instagram.com/p/DYxQDxwlUP_/ — eran dos menciones distintas,
    pero se fusionaban en una si el fingerprint no incluía author."""
    run_id = db.start_run(tmp_db, "seed", None)

    # Mismo URL, mismo texto, autores distintos
    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(
                mid="m-1",
                url="https://www.instagram.com/p/DYxQDxwlUP_/",
                text="❤️❤️❤️❤️❤️",
                author="catherine_zik_oppenheimer",
                published_at="2026-06-02T10:00:00+00:00"
            ),
            _mention(
                mid="m-2",
                url="https://www.instagram.com/p/DYxQDxwlUP_/",
                text="❤️❤️❤️❤️❤️",
                author="valentina_ahumada977",
                published_at="2026-05-29T14:30:00+00:00"
            ),
        ],
        run_id,
    )

    # Ambos deben insertarse, NO hay duplicado
    assert (ins, dup) == (2, 0)
    assert len(db.all_mentions(tmp_db)) == 2


def test_insertar_menciones_nuevas(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert (ins, dup) == (1, 0)
    assert len(db.all_mentions(tmp_db)) == 1


def test_mencion_sin_brand_explicito_usa_el_default(tmp_db):
    """Una mención sin 'brand' (compatibilidad con el pipeline pre-multimarca)
    debe quedar etiquetada con DEFAULT_BRAND, no con NULL."""
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert db.all_mentions(tmp_db)[0]["brand"] == DEFAULT_BRAND


def test_all_mentions_filtra_por_marca(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [
        _mention(mid="m-1", brand="Avianca"),
        _mention(mid="m-2", brand="LATAM"),
    ], run_id)

    assert len(db.all_mentions(tmp_db)) == 2
    assert len(db.all_mentions(tmp_db, brand="Avianca")) == 1
    assert len(db.all_mentions(tmp_db, brand="LATAM")) == 1
    assert db.all_mentions(tmp_db, brand="LATAM")[0]["id"] == "m-2"


def test_pending_classification_filtra_por_marca(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [
        _mention(mid="m-1", brand="Avianca"),
        _mention(mid="m-2", brand="LATAM"),
    ], run_id)

    assert len(db.pending_classification(tmp_db)) == 2
    assert len(db.pending_classification(tmp_db, brand="Avianca")) == 1
    assert len(db.pending_classification(tmp_db, brand="LATAM")) == 1


def test_start_run_guarda_la_marca(tmp_db):
    run_id = db.start_run(tmp_db, "weekly", None, brand="LATAM")
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["brand"] == "LATAM"


def test_start_run_sin_marca_usa_el_default(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["brand"] == DEFAULT_BRAND


def test_reinsertar_el_mismo_lote_es_idempotente(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    run_2 = db.start_run(tmp_db, "weekly", None)
    ins, dup = db.upsert_mentions(tmp_db, [_mention()], run_2)
    assert (ins, dup) == (0, 1)
    assert len(db.all_mentions(tmp_db)) == 1


def test_run_id_conserva_la_primera_corrida(tmp_db):
    """INSERT OR IGNORE preserva run_id y fetched_at de la primera corrida."""
    run_1 = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(fetched_at="2026-08-19T10:00:00+00:00")], run_1)

    run_2 = db.start_run(tmp_db, "weekly", None)
    db.upsert_mentions(tmp_db, [_mention(fetched_at="2026-08-20T15:30:00+00:00")], run_2)

    fila = db.all_mentions(tmp_db)[0]
    assert fila["run_id"] == run_1
    assert fila["fetched_at"] == "2026-08-19T10:00:00+00:00"


def test_mismo_url_distinto_texto_si_inserta(tmp_db):
    """Dos comentarios distintos pueden vivir en la misma URL — por eso el
    dedup va por fingerprint del contenido y no por source_url."""
    run_id = db.start_run(tmp_db, "seed", None)
    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(mid="m-1"),
            _mention(mid="m-2", text="Otro comentario totalmente diferente aquí"),
        ],
        run_id,
    )
    assert (ins, dup) == (2, 0)
    assert len(db.all_mentions(tmp_db)) == 2


def test_fingerprint_colision_regresion_prefijo_largo(tmp_db):
    """Regresión: dos comentarios en misma URL con prefijo largo (>80 chars)
    que divergen solo al final, deben tener fingerprints distintos y ambos insertarse.

    Antes del fix, fingerprint truncaba a 80 chars, causando una colisión falsa."""
    run_id = db.start_run(tmp_db, "seed", None)

    # Textos que comparten un prefijo muy largo, divergen solo al final
    prefix = "Avianca canceló mi vuelo y no me han dado respuesta desde hace más de una semana ya " * 2
    text1 = prefix + "esto es inaceptable"
    text2 = prefix + "solicito reembolso inmediato"

    ins, dup = db.upsert_mentions(
        tmp_db,
        [
            _mention(mid="m-1", text=text1),
            _mention(mid="m-2", text=text2),
        ],
        run_id,
    )

    # Ambos deben insertarse, NO debe haber duplicado falso
    assert (ins, dup) == (2, 0), f"expected (2, 0) but got ({ins}, {dup})"
    assert len(db.all_mentions(tmp_db)) == 2


def test_pending_classification_devuelve_solo_unclassified(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    pendientes = db.pending_classification(tmp_db)
    assert len(pendientes) == 1

    db.update_classification(tmp_db, pendientes[0]["id"], {
        "sentiment_positive": 0.0,
        "sentiment_negative": 0.9,
        "sentiment_neutral": 0.1,
        "emotion": "anger",
        "is_complaint": True,
        "complaint_driver": "equipaje",
    })

    assert db.pending_classification(tmp_db) == []
    fila = db.all_mentions(tmp_db)[0]
    assert fila["complaint_driver"] == "equipaje"
    assert fila["classification_status"] == "classified"
    assert fila["is_complaint"] == 1


def test_raw_se_guarda_y_recupera_como_dict(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)
    assert db.all_mentions(tmp_db)[0]["raw"] == {"foo": "bar"}


def test_finish_run_guarda_contadores(tmp_db):
    run_id = db.start_run(tmp_db, "backfill", "2026-04-19")
    db.finish_run(tmp_db, run_id, raw_count=10, filtered_count=3,
                  inserted_count=2, duplicate_count=1, notes="ok - backfill complete")
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["raw_count"] == 10
    assert fila["filtered_count"] == 3
    assert fila["inserted_count"] == 2
    assert fila["duplicate_count"] == 1
    assert fila["notes"] == "ok - backfill complete"
    assert fila["since"] == "2026-04-19"
    assert fila["finished_at"] is not None


def test_finish_run_guarda_short_text_count(tmp_db):
    run_id = db.start_run(tmp_db, "backfill", "2026-04-19")
    db.finish_run(tmp_db, run_id, raw_count=1310, filtered_count=71,
                  inserted_count=1000, duplicate_count=38, short_text_count=201)
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["short_text_count"] == 201


def test_finish_run_short_text_count_default_es_cero(tmp_db):
    """Llamadas existentes sin el parámetro nuevo no deben romperse."""
    run_id = db.start_run(tmp_db, "seed", None)
    db.finish_run(tmp_db, run_id, raw_count=5, filtered_count=1,
                  inserted_count=4, duplicate_count=0)
    fila = tmp_db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert fila["short_text_count"] == 0


def test_migracion_agrega_short_text_count_sin_perder_filas():
    """
    Migración aditiva: una DB con el schema viejo de `runs` (sin
    short_text_count) debe ganar la columna al pasar por init_db, sin
    perder ninguna fila existente. data/avianca.db tiene datos reales
    de scraping pagado — esto es lo que protege ese archivo.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE runs (
            id              TEXT PRIMARY KEY,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            mode            TEXT NOT NULL,
            since           TEXT,
            raw_count       INTEGER DEFAULT 0,
            filtered_count  INTEGER DEFAULT 0,
            inserted_count  INTEGER DEFAULT 0,
            duplicate_count INTEGER DEFAULT 0,
            notes           TEXT
        );
    """)
    conn.execute(
        "INSERT INTO runs (id, started_at, mode, raw_count) "
        "VALUES ('r1', '2026-01-01T00:00:00+00:00', 'seed', 42)"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)  # debe agregar la columna sin tocar el resto del schema

    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "short_text_count" in cols

    fila = conn.execute("SELECT * FROM runs WHERE id = 'r1'").fetchone()
    assert fila["id"] == "r1"
    assert fila["raw_count"] == 42
    assert fila["short_text_count"] == 0  # ADD COLUMN ... DEFAULT 0 rellena filas viejas

    # Idempotente: correrlo dos veces no falla ni duplica columnas.
    db.init_db(conn)
    cols_2 = [row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()]
    assert cols_2.count("short_text_count") == 1
    conn.close()


def test_migracion_agrega_columnas_de_engagement_sin_perder_filas():
    """
    Migración aditiva del desglose de engagement: una DB con el schema viejo
    de `mentions` (sin saves/views/reach_source) debe ganar esas tres
    columnas al pasar por init_db, sin perder ninguna fila existente —
    exactamente la misma protección que ya tiene short_text_count para
    `runs`. data/avianca.db tiene 1.261 filas de scraping ya pagado.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mentions (
            id                    TEXT PRIMARY KEY,
            fingerprint           TEXT NOT NULL UNIQUE,
            platform              TEXT NOT NULL,
            source_url            TEXT,
            text                  TEXT NOT NULL,
            author                TEXT,
            published_at          TEXT,
            date_confidence       TEXT NOT NULL,
            country               TEXT,
            likes                 INTEGER DEFAULT 0,
            shares                INTEGER DEFAULT 0,
            comments_count        INTEGER DEFAULT 0,
            sentiment_positive    REAL,
            sentiment_negative    REAL,
            sentiment_neutral     REAL,
            emotion               TEXT,
            is_complaint          INTEGER DEFAULT 0,
            complaint_driver      TEXT,
            classification_status TEXT NOT NULL,
            raw                   TEXT,
            fetched_at            TEXT,
            run_id                TEXT
        );
    """)
    conn.execute(
        "INSERT INTO mentions (id, fingerprint, platform, text, "
        "date_confidence, classification_status, likes) "
        "VALUES ('m1', 'fp1', 'tiktok', 'hola', 'exact', 'classified', 42)"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)  # debe agregar las columnas sin tocar el resto del schema

    cols = {row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()}
    assert {"saves", "views", "reach_source"} <= cols

    fila = conn.execute("SELECT * FROM mentions WHERE id = 'm1'").fetchone()
    assert fila["id"] == "m1"
    assert fila["likes"] == 42  # dato viejo intacto
    # Sin DEFAULT: filas viejas quedan NULL, no en cero — la ausencia no es un dato.
    assert fila["saves"] is None
    assert fila["views"] is None
    assert fila["reach_source"] is None

    # Idempotente: correrlo dos veces no falla ni duplica columnas.
    db.init_db(conn)
    cols_2 = [row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()]
    assert cols_2.count("saves") == 1
    assert cols_2.count("views") == 1
    assert cols_2.count("reach_source") == 1
    conn.close()


def test_migracion_agrega_source_account_sin_perder_filas():
    """
    Migración aditiva del registro de cuenta de origen (Tarea 1 — muestras
    comparables): una DB con el schema viejo de `mentions` (sin
    source_account) debe ganar esa columna al pasar por init_db, sin
    perder ninguna fila existente. Las filas viejas quedan NULL — no se
    inventa de qué cuenta salió un post ya scrapeado antes de que este
    campo existiera.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mentions (
            id                    TEXT PRIMARY KEY,
            fingerprint           TEXT NOT NULL UNIQUE,
            brand                 TEXT NOT NULL DEFAULT 'Avianca',
            platform              TEXT NOT NULL,
            source_url            TEXT,
            text                  TEXT NOT NULL,
            author                TEXT,
            published_at          TEXT,
            date_confidence       TEXT NOT NULL,
            country               TEXT,
            likes                 INTEGER DEFAULT 0,
            shares                INTEGER DEFAULT 0,
            comments_count        INTEGER DEFAULT 0,
            saves                 INTEGER,
            views                 INTEGER,
            reach_source          TEXT,
            sentiment_positive    REAL,
            sentiment_negative    REAL,
            sentiment_neutral     REAL,
            emotion               TEXT,
            is_complaint          INTEGER DEFAULT 0,
            complaint_driver      TEXT,
            classification_status TEXT NOT NULL,
            raw                   TEXT,
            fetched_at            TEXT,
            run_id                TEXT
        );
    """)
    conn.execute(
        "INSERT INTO mentions (id, fingerprint, platform, text, "
        "date_confidence, classification_status, author) "
        "VALUES ('m1', 'fp1', 'instagram', 'hola', 'exact', 'classified', 'usuario1')"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)  # debe agregar la columna sin tocar el resto del schema

    cols = {row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()}
    assert "source_account" in cols

    fila = conn.execute("SELECT * FROM mentions WHERE id = 'm1'").fetchone()
    assert fila["id"] == "m1"
    assert fila["author"] == "usuario1"  # dato viejo intacto
    assert fila["source_account"] is None  # fila vieja: no se inventa

    # Idempotente: correrlo dos veces no falla ni duplica la columna.
    db.init_db(conn)
    cols_2 = [row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()]
    assert cols_2.count("source_account") == 1
    conn.close()


def test_source_account_se_puebla_en_filas_nuevas(tmp_db):
    """En una DB nueva (schema ya con source_account desde el inicio), una
    fila insertada con ese campo lo conserva; sin el campo, queda NULL —
    nunca se inventa un valor por defecto."""
    run_id = db.start_run(tmp_db, "weekly", None, brand="Avianca")
    con_cuenta = _mention(mid="m-con-cuenta", url="https://ig.com/1")
    con_cuenta["platform"] = "instagram"
    con_cuenta["source_account"] = "avianca"
    sin_cuenta = _mention(mid="m-sin-cuenta", url="https://ig.com/2")
    db.upsert_mentions(tmp_db, [con_cuenta, sin_cuenta], run_id)

    fila_con = tmp_db.execute(
        "SELECT source_account FROM mentions WHERE id = 'm-con-cuenta'").fetchone()
    fila_sin = tmp_db.execute(
        "SELECT source_account FROM mentions WHERE id = 'm-sin-cuenta'").fetchone()
    assert fila_con["source_account"] == "avianca"
    assert fila_sin["source_account"] is None


def test_update_source_account_actualiza_solo_esa_columna(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    m = _mention(mid="m-1")
    m["platform"] = "instagram"
    db.upsert_mentions(tmp_db, [m], run_id)

    db.update_source_account(tmp_db, "m-1", "latamairlines_colombia")

    fila = tmp_db.execute("SELECT * FROM mentions WHERE id = 'm-1'").fetchone()
    assert fila["source_account"] == "latamairlines_colombia"
    assert fila["likes"] == 10  # nada más se tocó


def test_update_engagement_actualiza_solo_columnas_permitidas(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(mid="m-1")], run_id)

    db.update_engagement(tmp_db, "m-1", {
        "saves": 249, "views": 61500, "reach_source": "propio",
        # Clave ajena a _ENGAGEMENT_FIELDS: debe ignorarse, no romper el UPDATE.
        "text": "esto no debe escribirse",
    })

    fila = db.all_mentions(tmp_db)[0]
    assert fila["saves"] == 249
    assert fila["views"] == 61500
    assert fila["reach_source"] == "propio"
    assert fila["text"] == "Avianca me perdió la maleta en Bogotá"  # sin tocar


def test_update_engagement_es_idempotente(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(mid="m-1")], run_id)

    for _ in range(2):
        db.update_engagement(tmp_db, "m-1", {"saves": 249, "views": 61500, "reach_source": "propio"})

    fila = db.all_mentions(tmp_db)[0]
    assert fila["saves"] == 249
    assert fila["views"] == 61500
    assert len(db.all_mentions(tmp_db)) == 1  # no insertó filas nuevas


def test_update_engagement_sin_campos_permitidos_no_hace_nada(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention(mid="m-1")], run_id)

    db.update_engagement(tmp_db, "m-1", {"text": "intento de escribir algo no permitido"})

    fila = db.all_mentions(tmp_db)[0]
    assert fila["text"] == "Avianca me perdió la maleta en Bogotá"


# ── Tarea 1 (multi-marca): migración de brand + recálculo de fingerprint ──

def test_migracion_agrega_brand_a_runs_sin_perder_filas():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE runs (
            id              TEXT PRIMARY KEY,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            mode            TEXT NOT NULL,
            since           TEXT,
            raw_count       INTEGER DEFAULT 0,
            filtered_count  INTEGER DEFAULT 0,
            inserted_count  INTEGER DEFAULT 0,
            duplicate_count INTEGER DEFAULT 0,
            notes           TEXT
        );
    """)
    conn.execute(
        "INSERT INTO runs (id, started_at, mode, raw_count) "
        "VALUES ('r1', '2026-01-01T00:00:00+00:00', 'seed', 42)"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "brand" in cols
    fila = conn.execute("SELECT * FROM runs WHERE id = 'r1'").fetchone()
    assert fila["raw_count"] == 42  # dato viejo intacto
    assert fila["brand"] == DEFAULT_BRAND

    # Idempotente.
    db.init_db(conn)
    cols_2 = [row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()]
    assert cols_2.count("brand") == 1
    conn.close()


def test_migracion_agrega_brand_y_recalcula_fingerprint_sin_perder_filas():
    """
    Migración aditiva (Tarea 1, multi-marca): una DB con el schema viejo de
    `mentions` (sin `brand`, fingerprint calculado sin marca) debe ganar la
    columna `brand='Avianca'` y recalcular el fingerprint de cada fila con
    la nueva firma fingerprint(brand, platform, source_url, author, text),
    sin perder ninguna fila ni colapsar ninguna por colisión. Esto es lo
    que protege las 1.261 filas reales de data/avianca.db.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mentions (
            id                    TEXT PRIMARY KEY,
            fingerprint           TEXT NOT NULL UNIQUE,
            platform              TEXT NOT NULL,
            source_url            TEXT,
            text                  TEXT NOT NULL,
            author                TEXT,
            published_at          TEXT,
            date_confidence       TEXT NOT NULL,
            country               TEXT,
            likes                 INTEGER DEFAULT 0,
            shares                INTEGER DEFAULT 0,
            comments_count        INTEGER DEFAULT 0,
            sentiment_positive    REAL,
            sentiment_negative    REAL,
            sentiment_neutral     REAL,
            emotion               TEXT,
            is_complaint          INTEGER DEFAULT 0,
            complaint_driver      TEXT,
            classification_status TEXT NOT NULL,
            raw                   TEXT,
            fetched_at            TEXT,
            run_id                TEXT
        );
    """)
    old_fp_1 = "old-fingerprint-sin-marca-1"
    old_fp_2 = "old-fingerprint-sin-marca-2"
    conn.execute(
        "INSERT INTO mentions (id, fingerprint, platform, source_url, author, text, "
        "date_confidence, classification_status) VALUES "
        "('m1', ?, 'tiktok', 'https://x.com/1', 'user1', 'hola mundo', 'exact', 'classified')",
        (old_fp_1,),
    )
    conn.execute(
        "INSERT INTO mentions (id, fingerprint, platform, source_url, author, text, "
        "date_confidence, classification_status) VALUES "
        "('m2', ?, 'tiktok', 'https://x.com/1', 'user2', 'otro comentario', 'exact', 'classified')",
        (old_fp_2,),
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)  # debe agregar brand y recalcular fingerprint

    cols = {row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()}
    assert "brand" in cols

    filas = {r["id"]: r for r in conn.execute("SELECT * FROM mentions").fetchall()}
    assert len(filas) == 2
    assert filas["m1"]["brand"] == DEFAULT_BRAND
    assert filas["m2"]["brand"] == DEFAULT_BRAND

    # El fingerprint cambió (nueva firma con marca) y sigue siendo único.
    assert filas["m1"]["fingerprint"] != old_fp_1
    assert filas["m1"]["fingerprint"] == db.fingerprint(
        DEFAULT_BRAND, "tiktok", "https://x.com/1", "user1", "hola mundo"
    )
    distinct = conn.execute("SELECT COUNT(DISTINCT fingerprint) FROM mentions").fetchone()[0]
    assert distinct == 2

    # Idempotente: correrlo otra vez no rompe ni duplica la columna ni vuelve
    # a tocar el fingerprint ya recalculado.
    fp_antes_de_repetir = filas["m1"]["fingerprint"]
    db.init_db(conn)
    cols_2 = [row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()]
    assert cols_2.count("brand") == 1
    fila_m1 = conn.execute("SELECT * FROM mentions WHERE id = 'm1'").fetchone()
    assert fila_m1["fingerprint"] == fp_antes_de_repetir
    conn.close()


def test_migracion_indice_de_brand_no_revienta_en_db_vieja():
    """El índice sobre `brand` se crea después de garantizar que la columna
    existe — si se creara junto con el resto de SCHEMA (que corre antes de
    la migración), reventaría con 'no such column: brand' en una DB vieja."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mentions (
            id                    TEXT PRIMARY KEY,
            fingerprint           TEXT NOT NULL UNIQUE,
            platform              TEXT NOT NULL,
            source_url            TEXT,
            text                  TEXT NOT NULL,
            author                TEXT,
            published_at          TEXT,
            date_confidence       TEXT NOT NULL,
            country               TEXT,
            likes                 INTEGER DEFAULT 0,
            shares                INTEGER DEFAULT 0,
            comments_count        INTEGER DEFAULT 0,
            sentiment_positive    REAL,
            sentiment_negative    REAL,
            sentiment_neutral     REAL,
            emotion               TEXT,
            is_complaint          INTEGER DEFAULT 0,
            complaint_driver      TEXT,
            classification_status TEXT NOT NULL,
            raw                   TEXT,
            fetched_at            TEXT,
            run_id                TEXT
        );
    """)
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)  # no debe lanzar

    idx = {row[1] for row in conn.execute("PRAGMA index_list(mentions)").fetchall()}
    assert "idx_mentions_brand" in idx
    conn.close()


# ── Tarea 3 (relevancia social): exclusion_reason ──────────────────────

def test_migracion_agrega_exclusion_reason_sin_perder_filas():
    """
    Migración aditiva de exclusion_reason (Tarea 3 — corrección de
    relevancia social): una DB con el schema viejo de `mentions` (sin esa
    columna) debe ganarla al pasar por init_db, sin perder ninguna fila
    existente. Las filas viejas quedan NULL — "incluida", nunca excluida
    por defecto.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mentions (
            id                    TEXT PRIMARY KEY,
            fingerprint           TEXT NOT NULL UNIQUE,
            brand                 TEXT NOT NULL DEFAULT 'Avianca',
            platform              TEXT NOT NULL,
            source_url            TEXT,
            text                  TEXT NOT NULL,
            author                TEXT,
            published_at          TEXT,
            date_confidence       TEXT NOT NULL,
            country               TEXT,
            likes                 INTEGER DEFAULT 0,
            shares                INTEGER DEFAULT 0,
            comments_count        INTEGER DEFAULT 0,
            sentiment_positive    REAL,
            sentiment_negative    REAL,
            sentiment_neutral     REAL,
            emotion               TEXT,
            is_complaint          INTEGER DEFAULT 0,
            complaint_driver      TEXT,
            classification_status TEXT NOT NULL,
            raw                   TEXT,
            fetched_at            TEXT,
            run_id                TEXT
        );
    """)
    conn.execute(
        "INSERT INTO mentions (id, fingerprint, platform, text, "
        "date_confidence, classification_status, author) "
        "VALUES ('m1', 'fp1', 'tiktok', 'hola', 'exact', 'classified', 'usuario1')"
    )
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init_db(conn)  # debe agregar la columna sin tocar el resto del schema

    cols = {row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()}
    assert "exclusion_reason" in cols

    fila = conn.execute("SELECT * FROM mentions WHERE id = 'm1'").fetchone()
    assert fila["id"] == "m1"
    assert fila["text"] == "hola"  # dato viejo intacto
    assert fila["exclusion_reason"] is None  # fila vieja: incluida por defecto

    # Idempotente: correrlo dos veces no falla ni duplica la columna.
    db.init_db(conn)
    cols_2 = [row[1] for row in conn.execute("PRAGMA table_info(mentions)").fetchall()]
    assert cols_2.count("exclusion_reason") == 1
    conn.close()


def test_exclusion_reason_es_none_por_defecto_en_filas_nuevas(tmp_db):
    run_id = db.start_run(tmp_db, "weekly", None, brand="Avianca")
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    fila = tmp_db.execute("SELECT exclusion_reason FROM mentions WHERE id = 'm-1'").fetchone()
    assert fila["exclusion_reason"] is None


def test_set_exclusion_reason_marca_solo_esa_columna(tmp_db):
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    db.set_exclusion_reason(tmp_db, "m-1", "sin_contexto_aeronautico")

    fila = tmp_db.execute("SELECT * FROM mentions WHERE id = 'm-1'").fetchone()
    assert fila["exclusion_reason"] == "sin_contexto_aeronautico"
    assert fila["likes"] == 10  # nada más se tocó
    assert fila["text"] == "Avianca me perdió la maleta en Bogotá"


def test_set_exclusion_reason_es_reversible(tmp_db):
    """Pasar None reincluye la fila — la exclusión no es definitiva."""
    run_id = db.start_run(tmp_db, "seed", None)
    db.upsert_mentions(tmp_db, [_mention()], run_id)

    db.set_exclusion_reason(tmp_db, "m-1", "sin_keyword")
    assert tmp_db.execute(
        "SELECT exclusion_reason FROM mentions WHERE id = 'm-1'"
    ).fetchone()["exclusion_reason"] == "sin_keyword"

    db.set_exclusion_reason(tmp_db, "m-1", None)
    assert tmp_db.execute(
        "SELECT exclusion_reason FROM mentions WHERE id = 'm-1'"
    ).fetchone()["exclusion_reason"] is None
