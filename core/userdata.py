"""Favoritos, notas personales, claves verificadas por el usuario, copias de seguridad y exportación."""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import bank, config, db, srs

USER_TABLES = ["exams", "exam_answers", "review_state", "favorites", "notes", "activity", "settings",
               "user_answer_keys", "ai_cache"]


# ------------------------------------------------------------------ favoritos y notas

def is_favorite(qid: str) -> bool:
    return db.scalar("SELECT 1 FROM favorites WHERE question_id=?", (qid,)) is not None


def toggle_favorite(qid: str) -> bool:
    if is_favorite(qid):
        db.execute("DELETE FROM favorites WHERE question_id=?", (qid,))
        return False
    db.execute("INSERT OR IGNORE INTO favorites VALUES (?,?)", (qid, srs.iso(srs.now())))
    return True


def favorite_ids(topic_id: str | None = None) -> list[str]:
    ids = [r[0] for r in db.query("SELECT question_id FROM favorites ORDER BY added_at DESC")]
    if topic_id:
        allowed = set(bank.question_ids_for_topics([topic_id], scoreable_only=False))
        ids = [i for i in ids if i in allowed]
    return ids


def get_note(qid: str) -> str:
    return db.scalar("SELECT text FROM notes WHERE question_id=?", (qid,), default="")


def save_note(qid: str, text: str) -> None:
    if text.strip():
        db.execute("INSERT INTO notes VALUES (?,?,?) ON CONFLICT(question_id) DO UPDATE SET text=excluded.text, updated_at=excluded.updated_at",
                   (qid, text.strip(), srs.iso(srs.now())))
    else:
        db.execute("DELETE FROM notes WHERE question_id=?", (qid,))


def set_user_answer_key(qid: str, letter: str, source: str) -> None:
    """El usuario confirma la solución de una pregunta pendiente tras consultarla en una fuente oficial."""
    db.execute("INSERT OR REPLACE INTO user_answer_keys VALUES (?,?,?,?)", (qid, letter, source, srs.iso(srs.now())))
    db.execute("""UPDATE questions SET correct_letter=?, status='verificada_usuario', status_reason=?
                  WHERE id=? AND status='pendiente'""", (letter, f"Solución introducida por el usuario ({source})", qid))


def remove_user_answer_key(qid: str) -> None:
    db.execute("DELETE FROM user_answer_keys WHERE question_id=?", (qid,))
    db.execute("""UPDATE questions SET correct_letter=NULL, status='pendiente', status_reason='Sin solucionario oficial en los documentos'
                  WHERE id=? AND status='verificada_usuario'""", (qid,))


# ------------------------------------------------------------------ copias de seguridad

def backup(reason: str = "manual") -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = config.BACKUP_DIR / f"oposiciones-{ts}-{reason}.db"
    src = sqlite3.connect(db.get_db_path())
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    src.close()
    out.close()
    prune_backups()
    return dst


def prune_backups(keep: int = 20) -> None:
    files = sorted(config.BACKUP_DIR.glob("oposiciones-*.db"))
    for f in files[:-keep]:
        f.unlink(missing_ok=True)


def list_backups() -> list[Path]:
    return sorted(config.BACKUP_DIR.glob("oposiciones-*.db"), reverse=True)


def auto_daily_backup() -> Path | None:
    today = datetime.now().strftime("%Y%m%d")
    if any(today in f.name for f in config.BACKUP_DIR.glob("oposiciones-*-auto.db")):
        return None
    if (db.scalar("SELECT COUNT(*) FROM exams", default=0) or 0) == 0:
        return None
    return backup("auto")


def restore_backup(path: Path) -> None:
    """Restaura SOLO los datos del usuario de una copia (el banco se mantiene)."""
    backup("antes-de-restaurar")
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    with db.tx() as con:
        for t in USER_TABLES:
            try:
                rows = src.execute(f"SELECT * FROM {t}").fetchall()
            except sqlite3.OperationalError:
                continue
            con.execute(f"DELETE FROM {t}")
            if rows:
                cols = rows[0].keys()
                con.executemany(f"INSERT INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                [tuple(r) for r in rows])
    src.close()


# ------------------------------------------------------------------ exportación

def export_progress_json() -> bytes:
    data = {"exportado": srs.iso(srs.now()), "version": 1}
    for t in USER_TABLES:
        data[t] = [dict(r) for r in db.query(f"SELECT * FROM {t}")]
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def import_progress_json(raw: bytes) -> None:
    data = json.loads(raw.decode("utf-8"))
    backup("antes-de-importar")
    with db.tx() as con:
        for t in USER_TABLES:
            rows = data.get(t)
            if rows is None:
                continue
            con.execute(f"DELETE FROM {t}")
            for r in rows:
                cols = list(r.keys())
                con.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols])


def export_excel() -> bytes:
    from . import stats
    from .exams import history
    buf = io.BytesIO()
    hist = pd.DataFrame([{k: v for k, v in h.items() if k not in ("config", "config_json", "topics_json")} for h in history()])
    with pd.ExcelWriter(buf) as xw:
        if not hist.empty:
            hist.to_excel(xw, sheet_name="Historial", index=False)
        pt = stats.per_topic()
        if not pt.empty:
            pt.drop(columns=["ultima"]).to_excel(xw, sheet_name="Por tema", index=False)
        f = stats.failed_questions_df()
        if not f.empty:
            f.to_excel(xw, sheet_name="Fallos", index=False)
        pd.DataFrame([stats.overview()]).to_excel(xw, sheet_name="Resumen", index=False)
    return buf.getvalue()


def export_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("progreso.json", export_progress_json())
        try:
            z.writestr("estadisticas.xlsx", export_excel())
        except Exception:
            pass
        if config.INVENTORY_MD.exists():
            z.write(config.INVENTORY_MD, "INVENTARIO.md")
    return buf.getvalue()
