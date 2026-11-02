"""Test personalizado mezclando temas."""
from __future__ import annotations

import streamlit as st

from core import bank, exams, srs
from ui import nav


def render() -> None:
    nav.page_header("Test aleatorio personalizado", "Combina temas, cantidad y tipo de preguntas. Solo preguntas reales con solución verificada.", "🎲")
    tps = bank.topics(include_empty=False)
    ids = [t["id"] for t in tps]
    all_on = st.toggle("Incluir todos los temas", value=True, key="al_all")
    sel_topics = ids if all_on else st.multiselect("Temas incluidos", ids, default=ids[:1],
                                                   format_func=lambda t: bank.topic_label(t), key="al_topics")
    c1, c2 = st.columns(2)
    with c1:
        n_choice = st.segmented_control("Número de preguntas", ["10", "20", "30", "50", "100", "Otra"], default="30", key="al_n")
        n = int(n_choice) if n_choice and n_choice != "Otra" else st.number_input("Cantidad", 1, 1000, 40, key="al_n_custom")
    with c2:
        sel = st.selectbox("Tipo de preguntas", list(exams.SELECTION_LABELS), format_func=lambda k: exams.SELECTION_LABELS[k],
                           index=0, key="al_sel")
    mode = nav.mode_picker("al_mode")
    tl = nav.timer_picker("al_timer", n)

    if not sel_topics:
        st.warning("Selecciona al menos un tema.")
        return
    preview = exams.select_questions(sel_topics, None, sel)
    avail = len(preview)
    st.markdown(f"Preguntas disponibles con estos criterios: **{avail}**"
                + (f" → el test tendrá **{min(n, avail)}**" if avail else ""))
    with st.expander("¿Cómo se eligen las preguntas?"):
        st.markdown(
            "- Nunca se repite una pregunta dentro del mismo examen, ni dos preguntas casi idénticas detectadas como duplicadas.\n"
            "- **Todas / nunca respondidas / acertadas**: se priorizan las que llevas más tiempo sin ver, para que cada test sea distinto del anterior.\n"
            "- **Falladas**: primero las que has fallado más veces.\n"
            "- **Mayor dificultad personal**: ordenadas por tu tasa de fallo (fallos+1)/(intentos+2).\n"
            f"- **Mezcla inteligente**: ~45 % repasos vencidos, ~30 % nuevas, ~15 % en aprendizaje, ~10 % dominadas.")
    if st.button("🚀 Empezar test", type="primary", disabled=not avail):
        qids = exams.select_questions(sel_topics, n, sel)
        title = f"Test personalizado · {len(qids)} preguntas · {exams.SELECTION_LABELS[sel].lower()}"
        nav.start_exam("aleatorio", mode, title, qids, sel_topics, time_limit_s=tl, extra={"selection": sel})
