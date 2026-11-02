"""Historial de exámenes con revisión completa (copia inmutable de cada examen)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import bank, exams
from ui import nav
from ui.components import empty_state, fmt_time, kpi_row, review_list


def render() -> None:
    nav.page_header("Historial de exámenes", "Cada examen guarda una copia de sus preguntas y respuestas: el resultado no cambia aunque vuelvas a responder.", "📜")
    hist = exams.history()
    if not hist:
        empty_state("Todavía no has finalizado ningún examen.", "📜")
        return
    kinds = sorted({h["kind"] for h in hist})
    k = st.segmented_control("Tipo", ["Todos"] + kinds, default="Todos",
                             format_func=lambda x: x if x == "Todos" else exams.KIND_LABELS.get(x, x), key="hi_k")
    rows = [h for h in hist if k in (None, "Todos") or h["kind"] == k]
    df = pd.DataFrame([{
        "id": h["id"], "Fecha": h["finished_at"][:16].replace("T", " "), "Tipo": exams.KIND_LABELS.get(h["kind"], h["kind"]),
        "Título": h["title"], "Temas": ", ".join(bank.topic_label(t, short=True) for t in h["topics"]) or "Varios",
        "Preguntas": h["n_questions"], "Aciertos": h["n_correct"], "Errores": h["n_wrong"], "Blanco": h["n_blank"],
        "Nota": h["grade"], "% acierto": h["pct"], "Tiempo": fmt_time(h["elapsed_s"]),
        "Modo": "Práctica" if h["mode"] == "practica" else "Examen"} for h in rows])
    st.caption("Selecciona una fila para revisar el examen.")
    ev = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", key="hi_tbl",
                      column_config={"id": None,
                                     "Nota": st.column_config.ProgressColumn("Nota", min_value=0, max_value=10, format="%.2f"),
                                     "% acierto": st.column_config.NumberColumn(format="%.0f %%")},
                      height=min(420, 40 + 35 * len(df)))
    sel = ev.selection.rows if ev and ev.selection else []
    if not sel:
        return
    eid = int(df.iloc[sel[0]]["id"])
    e = exams.get_exam(eid)
    answers = exams.get_answers(eid)
    res = exams.compute_result(answers, e["config"]["scoring"])
    st.subheader(e["title"])
    kpi_row([("Nota", f"{res.grade:.2f}", ""), ("Aciertos", str(res.correct), ""), ("Errores", str(res.wrong), ""),
             ("En blanco", str(res.blank), ""), ("Tiempo", fmt_time(e["elapsed_s"]), "")])
    wrong = [a["question_id"] for a in answers if a["selected"] is not None and not a["is_correct"]]
    if wrong and st.button(f"🔁 Repetir los {len(wrong)} fallos de este examen", type="primary"):
        nav.start_exam("fallos", "practica", f"Fallos de: {e['title']}", wrong, e["topics"])
    review_list(answers, key=f"hist{eid}")
