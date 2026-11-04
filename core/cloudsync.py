"""Sincroniza la base de datos con un repositorio privado de GitHub (solo en la nube).

Se activa si existen los secrets DATA_REPO ("usuario/repo") y DATA_DEPLOY_KEY (clave SSH de despliegue,
solo para ese repo) o GITHUB_TOKEN.
Al arrancar descarga oposiciones.db; tras cada escritura la sube (agrupando cambios).
En local, sin esos secrets, no hace nada.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import subprocess
import sys
import threading
import time
from pathlib import Path
import urllib.error
import urllib.request

from . import db

FILE = "oposiciones.db"
DELAY_S = 15

_cfg: dict | None = None
_sha: str | None = None
_dirty = threading.Event()
_started = False
_status = {"active": False, "pulling": False, "last_pull": None, "last_ok": None, "last_error": None,
           "secrets_error": None, "timings": {}}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def status() -> dict:
    """Estado de la sincronización: active=False si faltan los secrets o falló la descarga inicial."""
    return dict({"pulling": False, "timings": {}}, **_status, repo=_cfg["repo"] if _cfg else None, pending=_dirty.is_set())


def _publish_status() -> None:
    """Estado sin datos sensibles en static/sync-status.json (permite comprobar la nube desde fuera)."""
    try:
        info = {k: _status.get(k) for k in ("active", "pulling", "last_pull", "last_ok", "timings")}
        info["error"] = bool(_status["last_error"])
        info["error_msg"] = (_status["last_error"] or "")[:300]
        info["secrets"] = secrets_found()
        info["secrets_error"] = _status["secrets_error"]
        info["counts"] = {t: db.scalar(f"SELECT COUNT(*) FROM {t}", default=0) for t in ("exams", "exam_answers", "review_state")}
        d = Path(__file__).resolve().parent.parent / "static"
        d.mkdir(exist_ok=True)
        (d / "sync-status.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 - nunca debe afectar a la app
        pass


def _secret(key: str):
    """Busca el secret sin distinguir mayúsculas, también dentro de una sección [..] de secrets.toml."""
    v = os.environ.get(key)
    if v:
        return v
    try:
        import streamlit as st
        d = st.secrets.to_dict()
        _status["secrets_error"] = None
    except Exception as e:  # noqa: BLE001 - sin secrets.toml o con formato no válido
        _status["secrets_error"] = type(e).__name__  # sin el mensaje: podría citar parte de la clave
        return None
    tables = [d] + [x for x in d.values() if isinstance(x, dict)]
    for t in tables:
        for k, val in t.items():
            if k.strip().upper() == key and val:
                return val
    return None


def secrets_found() -> dict:
    return {k: bool(_secret(k)) for k in ("DATA_REPO", "DATA_DEPLOY_KEY", "GITHUB_TOKEN")}


def _api(method: str, body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{_cfg['repo']}/contents/{FILE}?ref={_cfg['branch']}",
        method=method, data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {_cfg['token']}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


GITHUB_HOST_KEY = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def _git(*args: str, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd or _cfg["dir"], env=_cfg["env"], capture_output=True, text=True,
                          timeout=60, check=True).stdout  # nunca esperar indefinidamente


def _setup_git(key: str) -> None:
    """Clave de despliegue (solo da acceso a DATA_REPO): se usa git por SSH, sin tokens."""
    d = Path(tempfile.mkdtemp(prefix="opos_sync_"))
    kf, kh = d / "key", d / "known_hosts"
    kf.write_bytes((key.strip().replace(chr(13), "") + chr(10)).encode())
    kf.chmod(0o600)
    kh.write_text(GITHUB_HOST_KEY + chr(10))
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
               GIT_SSH_COMMAND=f'ssh -i "{kf.as_posix()}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes '
                               f'-o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 '
                               f'-o UserKnownHostsFile="{kh.as_posix()}"')
    _cfg.update(dir=str(d / "repo"), env=env, url=_secret("DATA_GIT_URL") or f"git@github.com:{_cfg['repo']}.git")


def _git_api(method: str, body: dict | None = None):
    """Misma interfaz que `_api`, pero con git: un push solo prospera si nadie subió algo más nuevo."""
    d, br = Path(_cfg["dir"]), _cfg["branch"]
    if method == "GET":
        if not d.exists():
            _git("clone", "-q", "--depth", "1", "--branch", br, _cfg["url"], str(d), cwd=d.parent)
        f = d / FILE
        if not f.exists():
            raise urllib.error.HTTPError(_cfg["url"], 404, "no existe", {}, None)
        return {"sha": _git("rev-parse", "HEAD").strip(), "content": base64.b64encode(f.read_bytes()).decode()}
    (d / FILE).write_bytes(base64.b64decode(body["content"]))
    _git("add", FILE)
    _git("-c", "user.name=OposPro", "-c", "user.email=opospro@users.noreply.github.com", "commit", "-q", "-m", body["message"])
    try:
        _git("push", "-q", "origin", f"HEAD:{br}")
    except subprocess.CalledProcessError as e:
        _git("reset", "-q", "--soft", "HEAD~1")
        raise RuntimeError("GitHub rechazó la subida (¿hay datos más recientes desde otro dispositivo?). "
                           "No se sobrescribe nada; reinicia la app. " + (e.stderr or "")[-200:]) from None
    return {"content": {"sha": _git("rev-parse", "HEAD").strip()}}


def _call(method: str, body: dict | None = None):
    return _git_api(method, body) if _cfg.get("env") else _api(method, body)


def _pull() -> None:
    global _sha
    try:
        meta = _call("GET")
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
        db.invalidate()


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
    # sin bloquear la interfaz: la copia en caliente de SQLite ya es coherente por sí misma
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src, dst = db.connect(), sqlite3.connect(tmp)
    try:
        src.backup(dst)
        # solo el progreso: el banco de preguntas viene con cada despliegue (_refresh_bank al descargar).
        # Así cada subida pesa kilobytes en vez de megas (más rápida con datos móviles y el repo no crece).
        for t in db.BANK_TABLES:
            dst.execute(f"DELETE FROM {t}")
        dst.commit()
        dst.execute("VACUUM")
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
    _sha = _call("PUT", body)["content"]["sha"]


def _superseded() -> bool:
    """True si Streamlit recargó este módulo tras un despliegue: el hilo antiguo debe dejar paso al nuevo."""
    m = sys.modules.get(__name__)
    return m is None or m.__dict__ is not globals()


def _worker() -> None:
    while True:
        _dirty.wait()
        time.sleep(DELAY_S)
        if _superseded():
            return
        _dirty.clear()
        try:
            _push()
            _status.update(last_ok=_now(), last_error=None)
            _publish_status()
        except Exception as e:  # noqa: BLE001 - reintentar en el siguiente ciclo
            print(f"[cloudsync] error al subir: {e}")
            _status["last_error"] = f"{_now()} · {type(e).__name__}: {e}"
            _publish_status()
            _dirty.set()
            time.sleep(60)


def _timed_pull() -> None:
    t = time.time()
    _pull()
    _status.setdefault("timings", {})["descarga_progreso_s"] = round(time.time() - t, 1)


def _activate() -> None:
    _status.update(active=True, pulling=False, last_pull=_now(), last_error=None)
    db.init_db()
    db.add_write_hook(_dirty.set)
    threading.Thread(target=_worker, daemon=True, name="cloudsync").start()
    _publish_status()


def _pull_loop() -> None:
    """Descarga en segundo plano con reintentos: la app se abre sin esperar a GitHub.
    Hasta que la descarga termina bien no se sube nada, así nunca se sobrescribe el progreso guardado."""
    for i in range(10_000):
        if _superseded():
            return
        try:
            _timed_pull()
            _activate()
            return
        except Exception as e:  # noqa: BLE001
            _status["last_error"] = (f"{_now()} · no se pudo recuperar tu progreso de GitHub ({type(e).__name__}: "
                                     f"{str(e)[:150]}). Reintentando; mientras tanto lo que hagas NO se guarda en GitHub.")
            print(f"[cloudsync] {_status['last_error']}")
            _publish_status()
            time.sleep((5, 15, 30, 60)[min(i, 3)])


def start(background: bool = False) -> bool:
    """Activa la sincronización. Con background=True la descarga inicial no bloquea la interfaz."""
    global _cfg, _started
    if _status["active"] or _status.get("pulling") or (_started and _cfg is not None):
        return _status["active"]
    _started = True
    token, key, repo = _secret("GITHUB_TOKEN"), _secret("DATA_DEPLOY_KEY"), _secret("DATA_REPO")
    if not (repo and (token or key)):
        _publish_status()
        return False
    _cfg = {"token": token, "repo": repo, "branch": _secret("DATA_BRANCH") or "main"}
    if key and not token:
        _setup_git(key)
    if background:
        _status["pulling"] = True
        _publish_status()
        threading.Thread(target=_pull_loop, daemon=True, name="cloudsync-pull").start()
        return False
    try:
        _timed_pull()
    except Exception as e:  # noqa: BLE001
        # sin la copia de GitHub NO se sube nada: así no se sobrescribe el progreso guardado con datos antiguos
        _status["last_error"] = (f"{_now()} · no se pudo descargar el progreso ({type(e).__name__}: {e}). "
                                 "Sincronización detenida para no sobrescribir los datos de GitHub; reinicia la app.")
        print(f"[cloudsync] {_status['last_error']}")
        _publish_status()
        return False
    _activate()
    return True
