"""Plan de estudio: prioriza temas y propone acciones a partir de los datos reales del usuario."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from . import srs, stats


@dataclass
class Recommendation:
    title: str
    reason: str              # siempre con las cifras en las que se basa
    action: str              # identificador de acción para la interfaz
    topic_id: str | None = None
    icon: str = "📌"
    priority: float = 0.0


def topic_priorities() -> pd.DataFrame:
    """Puntuación de prioridad 0–100 por tema. Fórmula transparente:

    40 % rendimiento (100 − % de aciertos; sin datos = 50)
    20 % repasos vencidos (proporción sobre preguntas practicadas)
    20 % cobertura (proporción del tema aún no practicada)
    10 % tiempo sin practicar (hasta 14 días)
    10 % tendencia (si los últimos 20 aciertos van peor que la media)
    """
    df = stats.per_topic()
    if df.empty:
        return df
    now = datetime.now()

    def score(r):
        perf = 100 - r["pct"] if pd.notna(r["pct"]) else 50
        due = (r["pendientes_repaso"] / r["practicadas"] * 100) if r["practicadas"] else 0
        cov = (1 - r["practicadas"] / r["disponibles"]) * 100 if r["disponibles"] else 0
        if r["ultima"] is not None and pd.notna(r["ultima"]):
            days = (now - pd.Timestamp(r["ultima"]).to_pydatetime()).days
        else:
            days = 14
        rec = min(days, 14) / 14 * 100
        trend = 0.0
        if pd.notna(r["pct"]) and pd.notna(r["pct_reciente"]):
            trend = max(0.0, r["pct"] - r["pct_reciente"]) * 2
        return round(0.4 * perf + 0.2 * due + 0.2 * cov + 0.1 * rec + 0.1 * min(trend, 100), 1), days

    vals = df.apply(score, axis=1, result_type="expand")
    df["prioridad"], df["dias_sin_practicar"] = vals[0], vals[1]
    return df.sort_values("prioridad", ascending=False)


def recommendations(max_items: int = 5) -> list[Recommendation]:
    recs: list[Recommendation] = []
    pr = topic_priorities()
    due_all = srs.due_ids()
    fails = stats.failed_questions_df()
    if pr.empty:
        return recs
    practiced = pr[pr["respuestas"] > 0]

    if len(due_all):
        recs.append(Recommendation(
            "Haz tu repaso pendiente", f"Tienes {len(due_all)} preguntas con repaso programado para hoy o atrasado.",
            "repaso", icon="🔁", priority=95))

    if not practiced.empty:
        worst = practiced.sort_values("pct").iloc[0]
        if worst["pct"] is not None and worst["respuestas"] >= 5 and worst["pct"] < 75:
            recs.append(Recommendation(
                f"Refuerza {worst['tema']}",
                f"Es tu tema con peor resultado: {worst['pct']:.0f} % de aciertos en {int(worst['respuestas'])} respuestas.",
                "estudiar_tema", worst["topic_id"], "📘", 90))

    if not fails.empty:
        active = fails[fails["estado"] == "Fallada"]
        if len(active):
            recs.append(Recommendation(
                "Test de preguntas falladas",
                f"{len(active)} preguntas siguen marcadas como falladas (último intento incorrecto).",
                "fallos", icon="❌", priority=85))

    unseen = pr[pr["practicadas"] < pr["disponibles"]].sort_values("practicadas")
    if not unseen.empty:
        u = unseen.iloc[0]
        pend = int(u["disponibles"] - u["practicadas"])
        recs.append(Recommendation(
            f"Practica preguntas nuevas de {u['tema']}",
            f"Te quedan {pend} de {int(u['disponibles'])} preguntas de este tema sin responder nunca.",
            "nuevas_tema", u["topic_id"], "🆕", 70 + 10 * (u["practicadas"] == 0)))

    stale = practiced[practiced["dias_sin_practicar"] >= 7]
    if not stale.empty:
        s = stale.sort_values("dias_sin_practicar", ascending=False).iloc[0]
        recs.append(Recommendation(
            f"Vuelve a {s['tema']}", f"Llevas {int(s['dias_sin_practicar'])} días sin practicar este tema.",
            "tema_test", s["topic_id"], "⏳", 60))

    if not fails.empty:
        recs.append(Recommendation(
            "Revisa los conceptos de tus errores",
            "El resumen de errores agrupa tus fallos por apartado del temario para detectar patrones.",
            "resumen_errores", icon="🧠", priority=55))

    if not recs:
        recs.append(Recommendation("Empieza con un test", "Aún no hay respuestas registradas.", "test", icon="🚀", priority=50))
    recs.sort(key=lambda r: -r.priority)
    return recs[:max_items]
