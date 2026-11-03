"""Sincroniza la base de datos con un repositorio privado de GitHub (solo en la nube).

Se activa únicamente si existen los secrets GITHUB_TOKEN y DATA_REPO ("usuario/repo").
Al arrancar descarga oposiciones.db; tras cada escritura la sube (agrupando cambios).
En local, sin esos secrets, no hace nada.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import db

FILE = "oposiciones.db"
DELAY_S = 15

_cfg: dict | None = None
_sha: str | None = None
_dirty = threading.Event()
_started = False


def _secret(key: str):
    v = os.environ.get(key)
    if v:
        return v
    try:
        import streamlit as st
        return st.secrets.get(key)
    except Exception:  # noqa: BLE001 - sin secrets.toml
        return None


def _api(method: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{_cfg['repo']}/contents/{FILE}?ref={_cfg['branch']}",
        method=method, data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {_cfg['token']}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _pull() -> None:
    global _sha
    try:
        meta = _api("GET")
    except urllib.error.HTTPError as e:
        if e.code == 404:  # primera vez: se subirá la base actual
            _dirty.set()
            return
        raise
    _sha = meta["sha"]
    if meta.get("content"):
        data = base64.b64decode(meta["content"])
    else:  # ficheros > 1 MB: descargar por la URL directa
        req = urllib.request.Request(meta["download_url"], headers={"Authorization": f"Bearer {_cfg['token']}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    with db._lock:
        path = db.get_db_path()
        bundled = path.with_suffix(".bundled.db")
        bundled.write_bytes(path.read_bytes())  # banco de preguntas de la versión desplegada
        path.write_bytes(data)                  # progreso del usuario (repo privado)
        _refresh_bank(bundled)
        bundled.unlink(missing_ok=True)


def _refresh_bank(bundled) -> None:
    """Sustituye las tablas del banco (preguntas, temas…) por las de la versión desplegada,
    conservando intactas las tablas de progreso del usuario."""
    db.init_db()
    con = sqlite3.connect(db.get_db_path())
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("ATTACH DATABASE ? AS b", (str(bundled),))
        if not con.execute("SELECT COUNT(*) FROM b.questions").fetchone()[0]:
            return
        for t in db.BANK_TABLES:
            cols = [r[1] for r in con.execute(f"PRAGMA main.table_info({t})")]
            bcols = {r[1] for r in con.execute(f"PRAGMA b.table_info({t})")}
            common = ",".join(c for c in cols if c in bcols)
            con.execute(f"DELETE FROM main.{t}")
            con.execute(f"INSERT INTO main.{t}({common}) SELECT {common} FROM b.{t}")
        con.commit()
        con.execute("DETACH DATABASE b")
    finally:
        con.close()
    _dirty.set()


def _snapshot() -> bytes:
    with db._lock:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        src, dst = db.connect(), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    try:
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


def _push() -> None:
    global _sha
    body = {"message": "Progreso OposPro", "branch": _cfg["branch"],
            "content": base64.b64encode(_snapshot()).decode()}
    if _sha:
        body["sha"] = _sha
    _sha = _api("PUT", body)["content"]["sha"]


def _worker() -> None:
    while True:
        _dirty.wait()
        time.sleep(DELAY_S)
        _dirty.clear()
        try:
            _push()
        except Exception as e:  # noqa: BLE001 - reintentar en el siguiente ciclo
            print(f"[cloudsync] error al subir: {e}")
            _dirty.set()
            time.sleep(60)


def start() -> bool:
    """Descarga la base de datos y activa la subida automática. Devuelve True si está activo."""
    global _cfg, _started
    if _started:
        return _cfg is not None
    _started = True
    token, repo = _secret("GITHUB_TOKEN"), _secret("DATA_REPO")
    if not (token and repo):
        return False
    _cfg = {"token": token, "repo": repo, "branch": _secret("DATA_BRANCH") or "main"}
    _pull()
    db.init_db()
    db.add_write_hook(_dirty.set)
    threading.Thread(target=_worker, daemon=True, name="cloudsync").start()
    return True
