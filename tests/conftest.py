"""Las pruebas trabajan sobre una base de datos temporal: nunca tocan tu progreso real."""
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db, ingest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_db():
    from core import config
    tmpdir = Path(tempfile.mkdtemp(prefix="opos_test_"))
    tmp = tmpdir / "test.db"
    config.BACKUP_DIR = tmpdir / "backups"
    config.BACKUP_DIR.mkdir()
    config.INVENTORY_JSON = tmpdir / "inventario.json"
    config.INVENTORY_MD = tmpdir / "INVENTARIO.md"
    db.set_db_path(tmp)
    ingest.run(verbose=False)
    yield tmp


@pytest.fixture()
def clean_user():
    """Vacía las tablas del usuario antes de cada prueba que lo necesite."""
    from core.userdata import USER_TABLES
    with db.tx() as con:
        for t in USER_TABLES:
            con.execute(f"DELETE FROM {t}")
        con.execute("DELETE FROM sqlite_sequence WHERE name IN ('exams','activity')")
    yield
