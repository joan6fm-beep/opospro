"""Repetición espaciada (sistema de cajas tipo Leitner), transparente y configurable.

Reglas (valores por defecto, editables en Ajustes):
* Fallo  → la pregunta vuelve a la caja 0 y queda para repaso inmediato (prioritaria).
* Acierto → sube una caja y el próximo repaso se programa según el intervalo de esa caja.
* Si se acierta a la primera (sin fallos previos) empieza directamente en la caja `first_correct_box`.
* Caja ≥ `mastery_box` → pregunta DOMINADA.
* Una pregunta dominada que se vuelve a fallar regresa a la caja 0.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db

DEFAULTS = {
    "intervals": [0, 1, 3, 7, 15, 30],   # días de espera por caja (caja 0 … caja 5)
    "first_correct_box": 2,
    "mastery_box": 4,
}


def params() -> dict:
    p = dict(DEFAULTS)
    p.update(db.get_setting("srs", {}) or {})
    return p


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def record(question_id: str, correct: bool, con=None, when: datetime | None = None) -> None:
    """Actualiza el estado de repaso tras responder una pregunta."""
    p = params()
    t = when or now()
    own = con is None
    ctx = db.tx() if own else None
    con = ctx.__enter__() if own else con
    try:
        r = con.execute("SELECT * FROM review_state WHERE question_id=?", (question_id,)).fetchone()
        n_seen = (r["n_seen"] if r else 0) + 1
        n_ok = (r["n_correct"] if r else 0) + (1 if correct else 0)
        n_ko = (r["n_wrong"] if r else 0) + (0 if correct else 1)
        box = r["box"] if r else None
        if correct:
            streak = (r["streak"] if r else 0) + 1
            if box is None:
                box = p["first_correct_box"]
            else:
                box = min(box + 1, len(p["intervals"]) - 1)
            due = t + timedelta(days=p["intervals"][box])
        else:
            streak = 0
            box = 0
            due = t
        first_wrong = (r["first_wrong_at"] if r else None) or (None if correct else iso(t))
        last_wrong = iso(t) if not correct else (r["last_wrong_at"] if r else None)
        caw = (r["correct_after_wrong"] if r else 0) or 0
        if correct and n_ko > 0:
            caw += 1
        elif not correct:
            caw = 0
        con.execute("""INSERT INTO review_state(question_id,n_seen,n_correct,n_wrong,streak,box,due_at,last_seen,last_result,
                       first_wrong_at,last_wrong_at,correct_after_wrong) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(question_id) DO UPDATE SET n_seen=excluded.n_seen,n_correct=excluded.n_correct,
                       n_wrong=excluded.n_wrong,streak=excluded.streak,box=excluded.box,due_at=excluded.due_at,
                       last_seen=excluded.last_seen,last_result=excluded.last_result,first_wrong_at=excluded.first_wrong_at,
                       last_wrong_at=excluded.last_wrong_at,correct_after_wrong=excluded.correct_after_wrong""",
                    (question_id, n_seen, n_ok, n_ko, streak, box, iso(due), iso(t), 1 if correct else 0,
                     first_wrong, last_wrong, caw))
    finally:
        if own:
            ctx.__exit__(None, None, None)


def state_label(r) -> str:
    """Estado de aprendizaje legible de una fila de review_state (o None)."""
    if r is None or not r["n_seen"]:
        return "Nueva"
    p = params()
    if r["box"] >= p["mastery_box"]:
        return "Recuperada" if r["n_wrong"] else "Dominada"
    if r["last_result"] == 0:
        return "Fallada"
    return "Aprendiendo"


def all_states() -> dict[str, dict]:
    return {r["question_id"]: dict(r) for r in db.query("SELECT * FROM review_state")}


def due_ids(topic_ids: list[str] | None = None) -> list[str]:
    """Preguntas con repaso vencido (primero las falladas y las que llevan más tiempo esperando)."""
    from .bank import question_ids_for_topics
    allowed = set(question_ids_for_topics(topic_ids))
    rows = db.query("SELECT question_id FROM review_state WHERE due_at<=? ORDER BY box ASC, n_wrong DESC, due_at ASC",
                    (iso(now()),))
    return [r[0] for r in rows if r[0] in allowed]


def mastered_ids() -> list[str]:
    return [r[0] for r in db.query("SELECT question_id FROM review_state WHERE box>=?", (params()["mastery_box"],))]
