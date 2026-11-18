"""Exámenes de convocatoria reales: se hacen completos, en su orden original, y se corrigen con su solucionario."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import bank, exams, srs
from ui import nav
from ui.components import kpi_row
from ui.views.practicas import _errors, _solutions

KIND = "convocatoria"


def _attempts(test_id: str) -> list[dict]:
    return [h for h in exams.history(kind=KIND) if h["config"].get("test_id") == test_id]


def _exam(t: dict) -> None:
    qids = bank.test_question_ids(t["id"])
    all_ids = bank.test_question_ids(t["id"], scoreable_only=False)
    states = srs.all_states()
    failed = [i for i in qids if i in states and states[i]["n_wrong"] > 0 and states[i]["last_result"] == 0]
    hist = _attempts(t["id"])
    best = max((h["grade"] for h in hist), default=None)
    kpi_row([("Preguntas", str(len(qids)), f"de {len(all_ids)} del examen original"),
             ("Intentos", str(len(hist)), ""),
             ("Última nota", f"{hist[0]['grade']:.2f}" if hist else "—",
              f"{hist[0]['n_correct']} aciertos · {hist[0]['n_wrong']} fallos" if hist else ""),
             ("Mejor nota", f"{best:.2f}" if best is not None else "—", "sobre 10")])
    if len(qids) < len(all_ids):
        st.warning(f"{len(all_ids) - len(qids)} pregunta(s) marcadas para revisión: no puntúan hasta comprobarlas.")
    st.caption("Preguntas 1‑25 del examen y 26‑30 de reserva. Respuestas según el solucionario oficial. "
               "Corrección: 1 punto por acierto, sin penalización, nota sobre 10.")
    key = f"cv_{t['topic_id']}"
    mode = nav.mode_picker(f"{key}_mode", default="examen")
    tl = nav.timer_picker(f"{key}_timer", len(qids))
    c1, c2 = st.columns(2)
    extra = {"test_id": t["id"], "convocatoria": t["name"]}
    tid = t["topic_id"]
    if c1.button(f"▶️ Hacer el examen completo ({len(qids)})", key=f"{key}_go", type="primary", width="stretch"):
        nav.start_exam(KIND, mode, t["name"], qids, [tid], time_limit_s=tl, extra=extra)
    if c2.button(f"❌ Repetir falladas ({len(failed)})", key=f"{key}_ko", width="stretch", disabled=not failed):
        nav.start_exam("fallos", mode, f"{t['name']} · falladas", failed, [tid], time_limit_s=tl)
    qs = bank.get_questions(all_ids)
    n_err = sum(1 for i in qids if i in states and states[i]["n_wrong"] > 0)
    with st.expander(f"🔑 Consultar soluciones ({len(qids)}/{len(all_ids)})"):
        _solutions(qs, all_ids)
    with st.expander(f"🔍 Revisar mis errores ({n_err})"):
        _errors(qs, qids, states)
    if hist:
        st.markdown("**Resultados anteriores**")
        st.dataframe(pd.DataFrame([{
            "Fecha": h["finished_at"][:16].replace("T", " "), "Nota": h["grade"], "Aciertos": h["n_correct"],
            "Fallos": h["n_wrong"], "En blanco": h["n_blank"], "% acierto": h["pct"],
            "Modo": "Práctica" if h["mode"] == "practica" else "Examen"} for h in hist]),
            hide_index=True, width="stretch",
            column_config={"Nota": st.column_config.ProgressColumn("Nota", min_value=0, max_value=10, format="%.2f"),
                           "% acierto": st.column_config.NumberColumn(format="%.0f %%")})
        st.caption("La revisión pregunta a pregunta está en *Historial*.")


def render() -> None:
    nav.page_header("Exámenes de convocatoria", "Exámenes reales completos, con sus preguntas originales y su solucionario.", "🏛️")
    tests = bank.exam_tests()
    if not tests:
        st.info("No hay exámenes de convocatoria importados.", icon="📭")
        return
    names = {t["id"]: t["name"] for t in tests}
    sel = st.selectbox("Examen", list(names), format_func=names.get, key="cv_sel")
    _exam(next(t for t in tests if t["id"] == sel))
