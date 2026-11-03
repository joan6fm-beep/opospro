"""Si el banco de preguntas local cambió respecto al último commit, deja preparada en el índice de git
una copia de data/oposiciones.db SIN progreso del usuario (el repositorio de la app es público)."""
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())
from core.db import BANK_TABLES  # noqa: E402
from core.userdata import USER_TABLES  # noqa: E402

DB = "data/oposiciones.db"


def bank_hash(path):
    c = sqlite3.connect(path)
    h = hashlib.sha256()
    for t in BANK_TABLES:
        for r in c.execute(f"SELECT * FROM {t} ORDER BY 1"):
            h.update(repr(tuple(r)).encode())
    c.close()
    return h.hexdigest()


tmp = tempfile.mkdtemp()
head = os.path.join(tmp, "head.db")
with open(head, "wb") as f:
    f.write(subprocess.run(["git", "show", f"HEAD:{DB}"], capture_output=True, check=True).stdout)
if bank_hash(head) == bank_hash(DB):
    sys.exit(0)
clean = os.path.join(tmp, "clean.db")
s, d = sqlite3.connect(DB), sqlite3.connect(clean)
s.backup(d)
s.close()
for t in USER_TABLES:
    d.execute(f"DELETE FROM {t}")
d.commit()
d.execute("VACUUM")
d.close()
sha = subprocess.run(["git", "hash-object", "-w", clean], capture_output=True, text=True, check=True).stdout.strip()
subprocess.run(["git", "update-index", "--cacheinfo", f"100644,{sha},{DB}"], check=True)
print("banco actualizado (sin progreso)")
