"""Acceso a SQLite.

Dos grupos de tablas:
* Banco (documentos, temas, apartados, preguntas...): se regenera al importar documentos.
* Usuario (exámenes, respuestas, repasos, favoritos, notas...): nunca se borra al reimportar.
  Las preguntas se identifican con un hash estable de su contenido, así el progreso se conserva.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

BANK_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,            -- ruta relativa
    name TEXT, kind TEXT, topic_id TEXT, pages INTEGER, sha1 TEXT, size_bytes INTEGER
);
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY, anexo TEXT, number INTEGER, short_name TEXT, title TEXT,
    sort_order INTEGER, folder TEXT
);
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY, topic_id TEXT, doc_id TEXT, ord INTEGER, title TEXT,
    level INTEGER, page INTEGER, text TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, section_id INTEGER, topic_id TEXT, doc_id TEXT, page INTEGER, text TEXT
);
CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY, topic_id TEXT, name TEXT, doc_id TEXT, solution_doc_id TEXT,
    n_questions INTEGER, n_verified INTEGER, ord INTEGER
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, topic_id TEXT, stem TEXT, options_json TEXT,
    correct_letter TEXT, status TEXT, status_reason TEXT,
    official_justification TEXT, solution_doc_id TEXT, solution_page INTEGER,
    source_doc_id TEXT, source_page INTEGER, source_number INTEGER, dup_group TEXT
);
CREATE TABLE IF NOT EXISTS question_sources (
    question_id TEXT, test_id TEXT, position INTEGER, doc_id TEXT, page INTEGER, number INTEGER,
    PRIMARY KEY (test_id, position)
);
CREATE TABLE IF NOT EXISTS question_theory (
    question_id TEXT, chunk_id INTEGER, rank INTEGER, score REAL, PRIMARY KEY (question_id, rank)
);
CREATE TABLE IF NOT EXISTS esquemas (
    id INTEGER PRIMARY KEY, topic_id TEXT, path TEXT, ord INTEGER, label TEXT
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY, kind TEXT, doc_id TEXT, question_id TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_q_topic ON questions(topic_id);
CREATE INDEX IF NOT EXISTS ix_qs_q ON question_sources(question_id);
CREATE INDEX IF NOT EXISTS ix_chunks_topic ON chunks(topic_id);
"""

USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, mode TEXT, title TEXT, topics_json TEXT, config_json TEXT,
    status TEXT DEFAULT 'en_curso', current_index INTEGER DEFAULT 0,
    started_at TEXT, finished_at TEXT, time_limit_s INTEGER, elapsed_s INTEGER DEFAULT 0,
    n_questions INTEGER, n_correct INTEGER, n_wrong INTEGER, n_blank INTEGER,
    score REAL, max_score REAL, pct REAL
);
CREATE TABLE IF NOT EXISTS exam_answers (
    exam_id INTEGER, position INTEGER, question_id TEXT,
    selected TEXT, is_correct INTEGER, flagged INTEGER DEFAULT 0, answered_at TEXT,
    -- copia de la pregunta en el momento del examen (el historial no cambia aunque cambie el banco)
    topic_id TEXT, stem TEXT, options_json TEXT, correct_letter TEXT, justification TEXT,
    PRIMARY KEY (exam_id, position)
);
CREATE TABLE IF NOT EXISTS review_state (
    question_id TEXT PRIMARY KEY, n_seen INTEGER DEFAULT 0, n_correct INTEGER DEFAULT 0,
    n_wrong INTEGER DEFAULT 0, streak INTEGER DEFAULT 0, box INTEGER DEFAULT 0,
    due_at TEXT, last_seen TEXT, last_result INTEGER, first_wrong_at TEXT, last_wrong_at TEXT,
    correct_after_wrong INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS favorites (question_id TEXT PRIMARY KEY, added_at TEXT);
CREATE TABLE IF NOT EXISTS notes (question_id TEXT PRIMARY KEY, text TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, topic_id TEXT, day TEXT, seconds INTEGER, ts TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ai_cache (
    key TEXT PRIMARY KEY, text TEXT, model TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS user_answer_keys (
    question_id TEXT PRIMARY KEY, letter TEXT, source TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_ea_q ON exam_answers(question_id);
CREATE INDEX IF NOT EXISTS ix_exams_status ON exams(status);
"""

BANK_TABLES = ["documents", "topics", "sections", "chunks", "tests", "questions",
               "question_sources", "question_theory", "esquemas", "issues"]

_lock = threading.RLock()
_db_path: Path = config.DB_PATH


def set_db_path(path: Path) -> None:
    """Permite usar otra base de datos (pruebas)."""
    global _db_path
    _db_path = Path(path)
    init_db()


def get_db_path() -> Path:
    return _db_path


_write_hooks: list = []


def add_write_hook(fn) -> None:
    """Llama a `fn` tras cada transacción que modifica datos (sincronización en la nube)."""
    _write_hooks.append(fn)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=DELETE")  # más seguro en carpetas sincronizadas (OneDrive)
    return con


@contextmanager
def tx():
    with _lock:
        con = connect()
        try:
            yield con
            con.commit()
            if con.total_changes:
                for hook in _write_hooks:
                    hook()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def init_db() -> None:
    with tx() as con:
        con.executescript(BANK_SCHEMA)
        con.executescript(USER_SCHEMA)


def query(sql: str, params=()) -> list[sqlite3.Row]:
    with tx() as con:
        return con.execute(sql, params).fetchall()


def query_one(sql: str, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params=(), default=None):
    row = query_one(sql, params)
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql: str, params=()) -> int:
    with tx() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid


def get_setting(key: str, default=None):
    v = scalar("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(v) if v is not None else default


def set_setting(key: str, value) -> None:
    execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)))


def bank_is_empty() -> bool:
    return (scalar("SELECT COUNT(*) FROM questions", default=0) or 0) == 0


init_db()
