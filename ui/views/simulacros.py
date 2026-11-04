"""Simulacros de examen con criterios configurables (no oficiales)."""
from __future__ import annotations

import streamlit as st

from core import bank, db, exams
from ui import nav
from ui.components import fmt_time

PRESETS = {
    "Sin penalización": 0.0,
    "Cada 3 errores restan 1 acierto (−0,333)": 1 / 3,
    "Cada 4 errores restan 1 acierto (−0,25)": 0.25,
    "Personalizada": None,
}


def _topic_option(t: dict, tests: dict) -> str:
    """Etiqueta con el nº de preguntas; deja claro que el Tema 1 incluye su Parte 2."""
    names = tests.get(t["id"], [])
    extra = ""
    if len(names) > 1:
        extra = " · Parte 1 + Parte 2" if any("parte 2" in n.lower() for n in names) else f" · {len(names)} test"
    return f"{bank.topic_label(t['id'])} ({t['n_scoreable']} preg.{extra})"


def render() -> None:
    nav.page_header("Simulacros de examen", "Exámenes cronometrados en modo examen, con puntuación configurable.", "⏱️")
    st.warning("**Simulación.** Tus documentos no incluyen las bases de la convocatoria, así que los criterios de corrección "
               "son parámetros que eliges tú. Ajústalos a las bases oficiales cuando las tengas.")
    saved = db.get_setting("simulacro", {}) or {}
    tps = bank.topics(include_empty=False)
    ids = [t["id"] for t in tps]
    tests = bank.tests_by_topic()
    labels = {t["id"]: _topic_option(t, tests) for t in tps}
    with st.form("sim_form"):
        c1, c2 = st.columns(2)
        n = c1.number_input("Número de preguntas", 5, 500, int(saved.get("n", 50)), step=5)
        mins = c2.number_input("Tiempo máximo (minutos)", 1, 600, int(saved.get("mins", 60)), step=5)
        topics = st.multiselect("Temas incluidos", ids, default=[t for t in saved.get("topics", ids) if t in ids] or ids,
                                format_func=labels.get)
        c3, c4, c5 = st.columns(3)
        pc = c3.number_input("Puntos por acierto", 0.0, 10.0, float(saved.get("correct", 1.0)), step=0.1, format="%.3f")
        names = list(PRESETS)
        preset = c4.selectbox("Penalización por error", names, index=names.index(saved.get("preset", "Sin penalización"))
                              if saved.get("preset") in names else 0)
        custom = c5.number_input("Penalización personalizada", 0.0, 10.0, float(saved.get("wrong", 0.0)), step=0.05, format="%.3f")
        c6, c7 = st.columns(2)
        blank = c6.number_input("Puntos por pregunta en blanco", -10.0, 10.0, float(saved.get("blank", 0.0)), step=0.05, format="%.3f")
        sel = c7.selectbox("Selección de preguntas", [exams.SEL_ALL, exams.SEL_SMART, exams.SEL_NEW],
                           format_func=lambda k: exams.SELECTION_LABELS[k])
        go_ = st.form_submit_button("🚀 Empezar simulacro", type="primary")
    if go_:
        if not topics:
            st.error("Selecciona algún tema.")
            return
        wrong = PRESETS[preset] if PRESETS[preset] is not None else custom
        db.set_setting("simulacro", {"n": n, "mins": mins, "topics": topics, "correct": pc, "preset": preset,
                                     "wrong": custom, "blank": blank})
        qids = exams.select_questions(topics, int(n), sel)
        title = f"Simulacro · {len(qids)} preguntas · {mins} min"
        nav.start_exam("simulacro", "examen", title, qids, topics,
                       scoring=exams.Scoring(correct=pc, wrong=wrong, blank=blank, scale=10.0), time_limit_s=int(mins * 60),
                       extra={"simulacion": True})

    hist = exams.history(kind="simulacro")
    if hist:
        st.subheader("Simulacros anteriores")
        for h in hist[:10]:
            st.markdown(f"- {h['finished_at'][:16].replace('T', ' ')} · **nota {h['grade']:.2f}** · {h['n_correct']} aciertos, "
                        f"{h['n_wrong']} errores, {h['n_blank']} en blanco · {fmt_time(h['elapsed_s'])}")
