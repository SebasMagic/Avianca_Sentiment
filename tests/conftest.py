import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Conexión SQLite en disco temporal, con el schema v2 aplicado."""
    from store import db
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    yield conn
    conn.close()
