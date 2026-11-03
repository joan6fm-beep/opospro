"""Sincronización con GitHub simulada en memoria: nunca toca el repositorio real."""
import base64
import urllib.error

from core import cloudsync, db, userdata


class FakeGitHub:
    def __init__(self, data: bytes | None = None, fail: bool = False):
        self.data, self.sha, self.fail, self.puts = data, "s0", fail, 0

    def __call__(self, method, body=None):
        if self.fail:
            raise urllib.error.URLError("sin conexión")
        if method == "GET":
            if self.data is None:
                raise urllib.error.HTTPError("u", 404, "no", {}, None)
            return {"sha": self.sha, "content": base64.b64encode(self.data).decode()}
        assert body.get("sha") == (self.sha if self.data is not None else None)  # nunca sobrescribe a ciegas una versión distinta
        self.data, self.puts = base64.b64decode(body["content"]), self.puts + 1
        self.sha = f"s{self.puts}"
        return {"content": {"sha": self.sha}}


def _restart(monkeypatch, gh):
    """Simula un arranque nuevo del contenedor de Streamlit Cloud (BD desplegada sin progreso)."""
    with db.tx() as con:
        for t in userdata.USER_TABLES:
            con.execute(f"DELETE FROM {t}")
    db._write_hooks.clear()
    cloudsync._dirty.clear()
    monkeypatch.setattr(cloudsync, "_started", False)
    monkeypatch.setattr(cloudsync, "_cfg", None)
    monkeypatch.setattr(cloudsync, "_sha", None)
    monkeypatch.setattr(cloudsync, "_status", {"active": False, "last_pull": None, "last_ok": None, "last_error": None})
    monkeypatch.setattr(cloudsync, "_api", gh)
    monkeypatch.setattr(cloudsync, "_secret", lambda k: {"GITHUB_TOKEN": "t", "DATA_REPO": "u/r"}.get(k))
    monkeypatch.setattr(cloudsync.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    return cloudsync.start()


def test_progreso_sobrevive_reinicios(monkeypatch, clean_user):
    qids = [r[0] for r in db.query("SELECT id FROM questions LIMIT 2")]
    n_q = db.scalar("SELECT COUNT(*) FROM questions")
    gh = FakeGitHub()
    assert _restart(monkeypatch, gh)              # primera vez: no hay copia en GitHub
    userdata.toggle_favorite(qids[0])
    assert cloudsync._dirty.is_set()              # cada escritura programa la subida
    cloudsync._push()
    assert gh.puts == 1

    assert _restart(monkeypatch, gh)              # reinicio: se recupera el progreso
    assert userdata.favorite_ids() == [qids[0]]
    assert db.scalar("SELECT COUNT(*) FROM questions") == n_q   # banco intacto
    userdata.toggle_favorite(qids[1])
    cloudsync._push()

    assert _restart(monkeypatch, gh)
    assert sorted(userdata.favorite_ids()) == sorted(qids)
    assert cloudsync.status()["active"] and not cloudsync.status()["last_error"]
    db._write_hooks.clear()


def test_fallo_al_descargar_no_sobrescribe(monkeypatch, clean_user):
    gh = FakeGitHub(data=b"progreso-en-la-nube", fail=True)
    assert not _restart(monkeypatch, gh)
    userdata.toggle_favorite(db.scalar("SELECT id FROM questions LIMIT 1"))
    assert not cloudsync._dirty.is_set()          # no se programa ninguna subida
    assert gh.data == b"progreso-en-la-nube"
    assert "no se pudo descargar" in cloudsync.status()["last_error"]
    userdata.toggle_favorite(db.scalar("SELECT id FROM questions LIMIT 1"))
