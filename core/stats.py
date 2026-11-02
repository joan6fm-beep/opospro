"""Estadísticas personales calculadas a partir de las respuestas guardadas."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from . import bank, db, srs

# Una respuesta "cuenta" si se ha contestado (en cualquier examen) o si el examen ya se finalizó (en blanco).
ANSWERS_SQL = """
SELECT ea.*, e.kind, e.mode, e.status, e.started_at, e.finished_at,
       COALESCE(ea.answered_at, e.finished_at) AS ts
FROM exam_answers ea JOIN exams e ON e.id = ea.exam_id
WHERE ea.selected IS NOT NULL OR e.status='finalizado'
"""


def answers_df() -> pd.DataFrame:
    df = pd.DataFrame([dict(r) for r in db.query(ANSWERS_SQL)])
    if df.empty:
        return pd.DataFrame(columns=["exam_id", "question_id", "topic_id", "selected", "is_correct", "ts"])
    df["ts"] = pd.to_datetime(df["ts"])
    df["answered"] = df["selected"].notna()
    df["ok"] = df["answered"] & (df["is_correct"] == 1)
    df["ko"] = df["answered"] & (df["is_correct"] == 0)
    df["day"] = df["ts"].dt.date
    return df


def study_seconds() -> int:
    tests = db.scalar("SELECT COALESCE(SUM(elapsed_s),0) FROM exams", default=0)
    other = db.scalar("SELECT COALESCE(SUM(seconds),0) FROM activity WHERE kind!='test'", default=0)
    return int(tests + other)


def study_time_by_day(days: int = 30) -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).date().isoformat()
    rows = db.query("""SELECT substr(started_at,1,10) AS day, SUM(elapsed_s) AS s, 'Test' AS tipo FROM exams
                       WHERE substr(started_at,1,10)>=? GROUP BY day
                       UNION ALL
                       SELECT day, SUM(seconds) AS s, 'Temario' AS tipo FROM activity WHERE kind!='test' AND day>=? GROUP BY day""",
                    (since, since))
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return pd.DataFrame(columns=["day", "minutos", "tipo"])
    df["minutos"] = (df["s"].fillna(0) / 60).round(1)
    return df


def overview() -> dict:
    df = answers_df()
    finished = db.query("SELECT * FROM exams WHERE status='finalizado'")
    answered = int(df["answered"].sum()) if not df.empty else 0
    ok = int(df["ok"].sum()) if not df.empty else 0
    ko = int(df["ko"].sum()) if not df.empty else 0
    blank = int(((~df["answered"]) & (df["status"] == "finalizado")).sum()) if not df.empty else 0
    grades = []
    for e in finished:
        sc = 10.0
        if e["max_score"]:
            grades.append(max(0.0, e["score"] / e["max_score"] * sc))
    return {
        "exams": len(finished),
        "answered": answered,
        "correct": ok,
        "wrong": ko,
        "blank": blank,
        "pct": (ok / answered * 100) if answered else None,
        "avg_grade": (sum(grades) / len(grades)) if grades else None,
        "seconds": study_seconds(),
        "distinct_seen": int(df.loc[df["answered"], "question_id"].nunique()) if not df.empty else 0,
    }


def per_topic() -> pd.DataFrame:
    df = answers_df()
    states = srs.all_states()
    p = srs.params()
    now = srs.iso(srs.now())
    rows = []
    for t in bank.topics(include_empty=False):
        ids = set(bank.question_ids_for_topics([t["id"]]))
        sub = df[df["question_id"].isin(ids) & df["answered"]] if not df.empty else df
        n_ans = len(sub)
        ok = int(sub["ok"].sum()) if n_ans else 0
        st = [states[i] for i in ids if i in states and states[i]["n_seen"]]
        recent = sub.sort_values("ts").tail(20) if n_ans else sub
        last = sub["ts"].max() if n_ans else None
        rows.append({
            "topic_id": t["id"],
            "tema": bank.topic_label(t["id"], short=True),
            "nombre": t["short_name"],
            "disponibles": len(ids),
            "practicadas": len(st),
            "respuestas": n_ans,
            "aciertos": ok,
            "fallos": n_ans - ok,
            "pct": ok / n_ans * 100 if n_ans else None,
            "pct_reciente": float(recent["ok"].mean() * 100) if len(recent) else None,
            "dominadas": sum(1 for s in st if s["box"] >= p["mastery_box"]),
            "pendientes_repaso": sum(1 for s in st if s["due_at"] <= now),
            "falladas_activas": sum(1 for s in st if s["last_result"] == 0),
            "ultima": last,
        })
    return pd.DataFrame(rows)


def evolution(by: str = "exam") -> pd.DataFrame:
    """Evolución de % de aciertos por examen finalizado (o por día)."""
    rows = db.query("""SELECT id, kind, title, finished_at, n_correct, n_wrong, n_blank, n_questions, pct, score, max_score
                       FROM exams WHERE status='finalizado' ORDER BY finished_at""")
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    df["finished_at"] = pd.to_datetime(df["finished_at"])
    df["nota"] = (df["score"] / df["max_score"] * 10).clip(lower=0).round(2)
    df["n"] = range(1, len(df) + 1)
    if by == "day":
        a = answers_df()
        a = a[a["answered"]]
        if a.empty:
            return a
        g = a.groupby("day").agg(respuestas=("ok", "size"), aciertos=("ok", "sum")).reset_index()
        g["pct"] = g["aciertos"] / g["respuestas"] * 100
        return g
    return df


def best_worst_topics(min_answers: int = 5) -> tuple[dict | None, dict | None]:
    df = per_topic()
    if df.empty:
        return None, None
    d = df[df["respuestas"] >= min_answers]
    if d.empty:
        return None, None
    best = d.sort_values(["pct", "respuestas"], ascending=[False, False]).iloc[0].to_dict()
    worst = d.sort_values(["pct", "respuestas"], ascending=[True, False]).iloc[0].to_dict()
    return best, worst


def failed_questions_df() -> pd.DataFrame:
    """Preguntas falladas alguna vez con su estado de aprendizaje."""
    rows = db.query("SELECT * FROM review_state WHERE n_wrong>0")
    if not rows:
        return pd.DataFrame()
    qs = bank.get_questions([r["question_id"] for r in rows])
    out = []
    for r in rows:
        q = qs.get(r["question_id"])
        if not q:
            continue
        out.append({"question_id": q.id, "topic_id": q.topic_id, "tema": bank.topic_label(q.topic_id, short=True),
                    "enunciado": q.stem, "veces_fallada": r["n_wrong"], "aciertos": r["n_correct"],
                    "aciertos_posteriores": r["correct_after_wrong"], "ultima_vez": r["last_seen"],
                    "ultimo_fallo": r["last_wrong_at"], "estado": srs.state_label(r), "caja": r["box"],
                    "repaso": r["due_at"]})
    return pd.DataFrame(out)


def error_distribution() -> pd.DataFrame:
    df = answers_df()
    if df.empty:
        return df
    k = df[df["ko"]]
    if k.empty:
        return k
    g = k.groupby("topic_id").size().reset_index(name="fallos")
    g["tema"] = g["topic_id"].map(lambda t: bank.topic_label(t, short=True))
    return g
