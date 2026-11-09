"""Consultas sobre el banco de preguntas, temas y teoría."""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass

from . import db
from .extract.test_parser import LETTERS

SCOREABLE = ("verificada", "verificada_usuario")
SCOREABLE_SQL = "('verificada','verificada_usuario')"


@dataclass
class Question:
    id: str
    topic_id: str
    stem: str
    options: list[str]
    correct_letter: str | None
    status: str
    status_reason: str
    justification: str
    solution_doc_id: str | None
    solution_page: int | None
    source_doc_id: str
    source_page: int
    source_number: int
    dup_group: str

    @property
    def scoreable(self) -> bool:
        return self.status in SCOREABLE and self.correct_letter is not None

    @property
    def correct_index(self) -> int | None:
        return LETTERS.index(self.correct_letter) if self.correct_letter else None

    @property
    def correct_text(self) -> str:
        i = self.correct_index
        return self.options[i] if i is not None and i < len(self.options) else ""


def _row_to_q(r) -> Question:
    return Question(r["id"], r["topic_id"], r["stem"], json.loads(r["options_json"]), r["correct_letter"], r["status"],
                    r["status_reason"] or "", r["official_justification"] or "", r["solution_doc_id"], r["solution_page"],
                    r["source_doc_id"], r["source_page"], r["source_number"], r["dup_group"])


def get_question(qid: str) -> Question | None:
    r = db.query_one("SELECT * FROM questions WHERE id=?", (qid,))
    return _row_to_q(r) if r else None


def get_questions(qids: list[str]) -> dict[str, Question]:
    if not qids:
        return {}
    out = {}
    for i in range(0, len(qids), 500):
        part = qids[i:i + 500]
        rows = db.query(f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(part))})", part)
        out.update({r["id"]: _row_to_q(r) for r in rows})
    return out


@functools.lru_cache(maxsize=4)
def _topics_cached(gen: int) -> tuple[dict, ...]:
    rows = db.query("""
        SELECT t.*, (SELECT COUNT(DISTINCT qs.question_id) FROM question_sources qs JOIN tests ts ON ts.id=qs.test_id
                     JOIN questions q ON q.id=qs.question_id WHERE q.topic_id=t.id AND q.status IN """ + SCOREABLE_SQL + """) AS n_scoreable,
               (SELECT COUNT(DISTINCT qs.question_id) FROM question_sources qs JOIN tests ts ON ts.id=qs.test_id
                     JOIN questions q ON q.id=qs.question_id WHERE q.topic_id=t.id) AS n_total,
               (SELECT COUNT(*) FROM sections s WHERE s.topic_id=t.id) AS n_sections,
               (SELECT COUNT(*) FROM esquemas e WHERE e.topic_id=t.id) AS n_esquemas
        FROM topics t ORDER BY sort_order""")
    return tuple(dict(r) for r in rows)


def topics(include_empty: bool = True) -> list[dict]:
    """Temas con sus recuentos (cacheado en memoria hasta la siguiente escritura en la base de datos)."""
    out = [dict(t) for t in _topics_cached(db.generation())]
    return out if include_empty else [t for t in out if t["n_scoreable"] > 0]


def topic(tid: str) -> dict | None:
    return next((t for t in topics() if t["id"] == tid), None)


def topic_label(tid: str | None, short: bool = False) -> str:
    if not tid:
        return "—"
    t = next((x for x in _topics_cached(db.generation()) if x["id"] == tid), None)
    if not t:
        return tid
    if t["anexo"] in ("I", "II"):
        prefix = f"Tema {t['number']}" + (" · Anexo II" if t["anexo"] == "II" else "")
        return prefix if short else f"{prefix} — {t['short_name']}"
    return t["short_name"]


def topic_labels() -> dict[str, str]:
    return {t["id"]: topic_label(t["id"]) for t in topics()}


def question_ids_for_topics(topic_ids: list[str] | None, scoreable_only: bool = True) -> list[str]:
    return list(_qids_cached(db.generation(), tuple(topic_ids or ()), scoreable_only))


@functools.lru_cache(maxsize=64)
def _qids_cached(gen: int, topic_ids: tuple, scoreable_only: bool) -> tuple[str, ...]:
    sql = "SELECT DISTINCT qs.question_id FROM question_sources qs JOIN tests ts ON ts.id=qs.test_id JOIN questions q ON q.id=qs.question_id WHERE 1=1"
    params: list = []
    if topic_ids:
        sql += f" AND q.topic_id IN ({','.join('?' * len(topic_ids))})"
        params += list(topic_ids)
    if scoreable_only:
        sql += " AND q.status IN " + SCOREABLE_SQL
    return tuple(r[0] for r in db.query(sql, params))


def tests_for_topic(tid: str) -> list[dict]:
    """Test del tema, incluidos los combinados que contienen preguntas suyas (p. ej. «Test Tema 7 y 10»)."""
    return [dict(r) for r in db.query("""SELECT * FROM tests WHERE topic_id=? OR id IN (SELECT qs.test_id FROM question_sources qs
                                          JOIN questions q ON q.id=qs.question_id WHERE q.topic_id=?) ORDER BY ord""", (tid, tid))]


def test_by_doc(doc_id: str) -> dict | None:
    """Test importado a partir de un documento (comparación insensible a tildes y mayúsculas)."""
    from .extract.test_parser import normalize
    key = normalize(doc_id)
    return next((dict(r) for r in db.query("SELECT * FROM tests") if normalize(r["doc_id"] or "") == key), None)


@functools.lru_cache(maxsize=2)
def _tests_by_topic_cached(gen: int) -> dict:
    out: dict[str, list[str]] = {}
    for r in db.query("""SELECT DISTINCT q.topic_id, t.name, t.ord FROM tests t JOIN question_sources qs ON qs.test_id=t.id
                          JOIN questions q ON q.id=qs.question_id ORDER BY q.topic_id, t.ord"""):
        out.setdefault(r["topic_id"], []).append(r["name"])
    return out


def tests_by_topic() -> dict[str, list[str]]:
    """Nombres de los test de cada tema (p. ej. Tema 1 tiene «Parte 1» y «Parte 2»), cacheado en memoria."""
    return _tests_by_topic_cached(db.generation())


def test_question_ids(test_id: str, scoreable_only: bool = True) -> list[str]:
    sql = "SELECT qs.question_id FROM question_sources qs JOIN questions q ON q.id=qs.question_id WHERE qs.test_id=?"
    if scoreable_only:
        sql += " AND q.status IN " + SCOREABLE_SQL
    return [r[0] for r in db.query(sql + " ORDER BY qs.position", (test_id,))]


def question_sources(qid: str) -> list[dict]:
    return [dict(r) for r in db.query("""SELECT qs.*, t.name AS test_name, t.topic_id FROM question_sources qs
                                          JOIN tests t ON t.id=qs.test_id WHERE qs.question_id=?""", (qid,))]


def theory_for_question(qid: str, k: int = 3) -> list[dict]:
    return [dict(r) for r in db.query("""
        SELECT c.*, s.title AS section_title, qt.score, qt.rank FROM question_theory qt
        JOIN chunks c ON c.id=qt.chunk_id JOIN sections s ON s.id=c.section_id
        WHERE qt.question_id=? ORDER BY qt.rank LIMIT ?""", (qid, k))]


def sections_for_topic(tid: str) -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM sections WHERE topic_id=? ORDER BY id", (tid,))]


def questions_for_section(section_id: int) -> list[str]:
    return [r[0] for r in db.query("""SELECT DISTINCT qt.question_id FROM question_theory qt JOIN chunks c ON c.id=qt.chunk_id
                                       WHERE c.section_id=? AND qt.rank=0""", (section_id,))]


def esquemas_for_topic(tid: str) -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM esquemas WHERE topic_id=? ORDER BY ord", (tid,))]


def documents(kind: str | None = None, topic_id: str | None = None) -> list[dict]:
    sql, p = "SELECT * FROM documents WHERE 1=1", []
    if kind:
        sql += " AND kind=?"; p.append(kind)
    if topic_id:
        sql += " AND topic_id=?"; p.append(topic_id)
    return [dict(r) for r in db.query(sql + " ORDER BY id", p)]


def pending_questions() -> list[Question]:
    return [_row_to_q(r) for r in db.query("SELECT * FROM questions WHERE status NOT IN " + SCOREABLE_SQL + " ORDER BY source_doc_id, source_number")]


def doc_label(doc_id: str | None) -> str:
    if not doc_id:
        return "—"
    return doc_id.split("/")[-1].rsplit(".", 1)[0]
