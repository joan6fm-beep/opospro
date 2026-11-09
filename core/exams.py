"""Creación de exámenes, selección de preguntas, respuestas, corrección y recuperación."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime

from . import bank, db, srs
from .extract.test_parser import LETTERS

# Tipos de selección de preguntas
SEL_ALL = "todas"
SEL_NEW = "nunca"
SEL_FAILED = "falladas"
SEL_CORRECT = "acertadas"
SEL_HARD = "dificiles"
SEL_SMART = "inteligente"
SEL_DUE = "repaso"

SELECTION_LABELS = {
    SEL_ALL: "Todas las disponibles",
    SEL_NEW: "Nunca respondidas",
    SEL_FAILED: "Falladas alguna vez",
    SEL_CORRECT: "Acertadas anteriormente",
    SEL_HARD: "Mayor dificultad personal",
    SEL_SMART: "Mezcla inteligente",
    SEL_DUE: "Repasos pendientes (hoy)",
}


@dataclass
class Scoring:
    correct: float = 1.0
    wrong: float = 0.0          # penalización (valor positivo que se resta)
    blank: float = 0.0
    scale: float = 10.0         # nota sobre…

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class ExamResult:
    n: int
    correct: int
    wrong: int
    blank: int
    score: float
    max_score: float
    grade: float
    pct: float


def _weighted_sample(ids: list[str], weights: dict[str, float], k: int, rng: random.Random) -> list[str]:
    """Muestreo sin reemplazo con pesos (Efraimidis–Spirakis)."""
    keyed = [(rng.random() ** (1.0 / max(weights.get(i, 1.0), 1e-6)), i) for i in ids]
    keyed.sort(reverse=True)
    return [i for _, i in keyed[:k]]


def _freshness_weights(ids: list[str], states: dict[str, dict]) -> dict[str, float]:
    """Favorece preguntas no vistas recientemente para que cada test sea distinto del anterior."""
    now = datetime.now()
    w = {}
    for i in ids:
        s = states.get(i)
        if not s or not s.get("last_seen"):
            w[i] = 3.0
        else:
            days = max((now - datetime.fromisoformat(s["last_seen"])).total_seconds() / 86400, 0)
            w[i] = 0.4 + min(days, 14) / 14 * 2.0
    return w


def _dedupe_groups(ids: list[str]) -> list[str]:
    """Evita incluir en el mismo examen dos preguntas casi idénticas (mismo grupo de duplicados)."""
    qs = bank.get_questions(ids)
    seen, out = set(), []
    for i in ids:
        g = qs[i].dup_group if i in qs else i
        if g in seen:
            continue
        seen.add(g)
        out.append(i)
    return out


def select_questions(topic_ids: list[str] | None, n: int | None, selection: str = SEL_ALL,
                     seed: int | None = None, exclude: set[str] | None = None) -> list[str]:
    rng = random.Random(seed)
    pool = bank.question_ids_for_topics(topic_ids)
    if exclude:
        pool = [i for i in pool if i not in exclude]
    states = srs.all_states()
    p = srs.params()

    def seen(i): return i in states and states[i]["n_seen"] > 0

    if selection == SEL_NEW:
        pool = [i for i in pool if not seen(i)]
    elif selection == SEL_FAILED:
        pool = [i for i in pool if seen(i) and states[i]["n_wrong"] > 0]
    elif selection == SEL_CORRECT:
        pool = [i for i in pool if seen(i) and states[i]["n_correct"] > 0]
    elif selection == SEL_DUE:
        due = set(srs.due_ids(topic_ids))
        pool = [i for i in pool if i in due]

    rng.shuffle(pool)
    pool = _dedupe_groups(pool)
    k = len(pool) if n is None else min(n, len(pool))

    if selection == SEL_HARD:
        def difficulty(i):
            s = states.get(i)
            if not s or not s["n_seen"]:
                return 0.35  # sin datos: dificultad media-baja
            return (s["n_wrong"] + 1) / (s["n_seen"] + 2) + 0.05 * s["n_wrong"]
        pool = [i for i in pool if seen(i)] or pool
        pool.sort(key=lambda i: (-difficulty(i), rng.random()))
        return pool[:k]

    if selection == SEL_SMART:
        now = srs.iso(srs.now())
        due = [i for i in pool if seen(i) and states[i]["due_at"] <= now]
        due.sort(key=lambda i: (states[i]["box"], -states[i]["n_wrong"]))
        new = [i for i in pool if not seen(i)]
        learning = [i for i in pool if seen(i) and i not in due and states[i]["box"] < p["mastery_box"]]
        mastered = [i for i in pool if seen(i) and i not in due and states[i]["box"] >= p["mastery_box"]]
        quotas = [(due, 0.45), (new, 0.30), (learning, 0.15), (mastered, 0.10)]
        chosen: list[str] = []
        for bucket, frac in quotas:
            chosen += bucket[: int(round(k * frac))]
        rest = [i for i in due + new + learning + mastered if i not in chosen]
        chosen += rest[: k - len(chosen)]
        chosen = chosen[:k]
        rng.shuffle(chosen)
        return chosen

    if selection in (SEL_FAILED, SEL_DUE):
        pool.sort(key=lambda i: (-(states[i]["n_wrong"] if i in states else 0), rng.random()))
        sel = pool[:k]
        rng.shuffle(sel)
        return sel

    return _weighted_sample(pool, _freshness_weights(pool, states), k, rng)


# ------------------------------------------------------------------ ciclo de vida del examen

def create_exam(kind: str, mode: str, title: str, question_ids: list[str], topic_ids: list[str] | None = None,
                scoring: Scoring | None = None, time_limit_s: int | None = None, shuffle: bool = False,
                extra: dict | None = None) -> int:
    """Crea un examen guardado en la base de datos (recuperable si se cierra la aplicación)."""
    if not question_ids:
        raise ValueError("No hay preguntas disponibles con esos criterios.")
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("Preguntas repetidas en el examen")
    qs = bank.get_questions(question_ids)
    question_ids = [i for i in question_ids if i in qs and qs[i].scoreable]
    if shuffle:
        random.shuffle(question_ids)
    cfg = {"scoring": (scoring or Scoring()).to_dict(), **(extra or {})}
    with db.tx() as con:
        cur = con.execute(
            """INSERT INTO exams(kind,mode,title,topics_json,config_json,status,current_index,started_at,time_limit_s,
               elapsed_s,n_questions) VALUES (?,?,?,?,?,'en_curso',0,?,?,0,?)""",
            (kind, mode, title, json.dumps(topic_ids or []), json.dumps(cfg), srs.iso(srs.now()), time_limit_s,
             len(question_ids)))
        eid = cur.lastrowid
        con.executemany(
            """INSERT INTO exam_answers(exam_id,position,question_id,selected,is_correct,flagged,topic_id,stem,options_json,
               correct_letter,justification) VALUES (?,?,?,NULL,NULL,0,?,?,?,?,?)""",
            [(eid, pos, q.id, q.topic_id, q.stem, json.dumps(q.options, ensure_ascii=False), q.correct_letter,
              q.justification) for pos, q in enumerate(qs[i] for i in question_ids)])
    return eid


def get_exam(eid: int) -> dict | None:
    r = db.query_one("SELECT * FROM exams WHERE id=?", (eid,))
    if not r:
        return None
    e = dict(r)
    e["config"] = json.loads(e["config_json"] or "{}")
    e["topics"] = json.loads(e["topics_json"] or "[]")
    return e


def get_answers(eid: int) -> list[dict]:
    out = []
    for r in db.query("SELECT * FROM exam_answers WHERE exam_id=? ORDER BY position", (eid,)):
        d = dict(r)
        d["options"] = json.loads(d["options_json"])
        out.append(d)
    return out


def answer(eid: int, position: int, letter: str | None) -> bool | None:
    """Guarda la respuesta. En modo práctica la respuesta queda fijada y actualiza el repaso al momento."""
    e = get_exam(eid)
    if not e or e["status"] != "en_curso":
        return None
    with db.tx() as con:
        a = con.execute("SELECT * FROM exam_answers WHERE exam_id=? AND position=?", (eid, position)).fetchone()
        if a is None:
            return None
        if e["mode"] == "practica" and a["selected"] is not None:
            return bool(a["is_correct"])  # ya contestada: no se puede cambiar en práctica
        ok = None if letter is None else (letter == a["correct_letter"])
        con.execute("UPDATE exam_answers SET selected=?, is_correct=?, answered_at=? WHERE exam_id=? AND position=?",
                    (letter, None if ok is None else int(ok), srs.iso(srs.now()), eid, position))
        if e["mode"] == "practica" and letter is not None:
            srs.record(a["question_id"], ok, con=con)
    return ok


def set_flag(eid: int, position: int, flagged: bool) -> None:
    db.execute("UPDATE exam_answers SET flagged=? WHERE exam_id=? AND position=?", (int(flagged), eid, position))


def set_position(eid: int, position: int) -> None:
    db.execute("UPDATE exams SET current_index=? WHERE id=?", (position, eid))


def add_elapsed(eid: int, seconds: int) -> None:
    if seconds > 0:
        db.execute("UPDATE exams SET elapsed_s=COALESCE(elapsed_s,0)+? WHERE id=? AND status='en_curso'", (int(seconds), eid))


def compute_result(answers: list[dict], scoring: dict) -> ExamResult:
    n = len(answers)
    c = sum(1 for a in answers if a["selected"] is not None and a["is_correct"])
    w = sum(1 for a in answers if a["selected"] is not None and not a["is_correct"])
    b = n - c - w
    score = c * scoring["correct"] - w * scoring["wrong"] + b * scoring.get("blank", 0.0)
    max_score = n * scoring["correct"]
    grade = max(0.0, score / max_score * scoring.get("scale", 10.0)) if max_score else 0.0
    pct = c / n * 100 if n else 0.0
    return ExamResult(n, c, w, b, round(score, 3), round(max_score, 3), round(grade, 2), round(pct, 1))


def finish(eid: int) -> ExamResult:
    e = get_exam(eid)
    answers = get_answers(eid)
    res = compute_result(answers, e["config"]["scoring"])
    if e["status"] != "en_curso":
        return res
    with db.tx() as con:
        if e["mode"] == "examen":
            for a in answers:
                if a["selected"] is not None:
                    srs.record(a["question_id"], bool(a["is_correct"]), con=con)
        con.execute("""UPDATE exams SET status='finalizado', finished_at=?, n_correct=?, n_wrong=?, n_blank=?, score=?,
                       max_score=?, pct=? WHERE id=?""",
                    (srs.iso(srs.now()), res.correct, res.wrong, res.blank, res.score, res.max_score, res.pct, eid))
        con.execute("INSERT INTO activity(kind,topic_id,day,seconds,ts) VALUES ('test',NULL,?,?,?)",
                    (srs.now().date().isoformat(), int(e["elapsed_s"] or 0), srs.iso(srs.now())))
    return res


def abandon(eid: int) -> None:
    db.execute("UPDATE exams SET status='abandonado', finished_at=? WHERE id=? AND status='en_curso'", (srs.iso(srs.now()), eid))


def open_exams() -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM exams WHERE status='en_curso' ORDER BY id DESC")]


def history(limit: int | None = None, kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM exams WHERE status='finalizado'"
    p: list = []
    if kind:
        sql += " AND kind=?"; p.append(kind)
    sql += " ORDER BY finished_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in db.query(sql, p)]
    for r in rows:
        r["config"] = json.loads(r["config_json"] or "{}")
        r["topics"] = json.loads(r["topics_json"] or "[]")
        sc = r["config"].get("scoring", {"correct": 1, "scale": 10})
        r["grade"] = round(max(0.0, (r["score"] or 0) / r["max_score"] * sc.get("scale", 10)), 2) if r["max_score"] else 0
    return rows


def letter_of(i: int) -> str:
    return LETTERS[i]


KIND_LABELS = {
    "tema_original": "Test original",
    "tema_aleatorio": "Test del tema",
    "aleatorio": "Test personalizado",
    "fallos": "Repaso de fallos",
    "favoritas": "Favoritas",
    "simulacro": "Simulacro",
    "repaso": "Repaso inteligente",
    "nuevas": "Preguntas nuevas",
    "practica": "Práctica de clase",
}
