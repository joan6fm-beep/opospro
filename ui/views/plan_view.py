"""Mi plan de estudio."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import plan
from ui import nav, theme
from ui.components import esc
from ui.views.inicio import run_recommendation


def render() -> None:
    nav.page_header("Mi plan de estudio", "Recomendaciones basadas solo en tus resultados reales.", "🗓️")
    st.markdown("### HOY TE RECOMENDAMOS")
    recs = plan.recommendations(6)
    cols = st.columns(2)
    for i, r in enumerate(recs):
        with cols[i % 2], st.container(border=True):
            st.markdown(f"#### {r.icon} {esc(r.title)}")
            st.caption(r.reason)
            if st.button("Empezar", key=f"plan_{i}", type="primary" if i == 0 else "secondary"):
                run_recommendation(r)

    pr = plan.topic_priorities()
    if pr.empty:
        return
    st.markdown("### Prioridad de temas")
    d = pr.sort_values("prioridad")
    fig = go.Figure(go.Bar(
        y=d["tema"], x=d["prioridad"], orientation="h", marker_cornerradius=4,
        marker_color=[theme.BLUE_SEQ[min(6, 1 + int(p // 17))] for p in d["prioridad"]],
        customdata=d[["nombre", "pct", "pendientes_repaso", "practicadas", "disponibles", "dias_sin_practicar"]],
        hovertemplate=("%{y} · %{customdata[0]}<br>Prioridad %{x:.0f}/100<br>Aciertos: %{customdata[1]:.0f} %<br>"
                       "Repasos pendientes: %{customdata[2]}<br>Practicadas: %{customdata[3]}/%{customdata[4]}<br>"
                       "Días sin practicar: %{customdata[5]}<extra></extra>")))
    fig.update_layout(height=90 + 34 * len(d), title="Cuanto más larga la barra, antes conviene trabajar ese tema",
                      xaxis=dict(range=[0, 100]))
    theme.chart(fig)
    with st.expander("¿Cómo se calcula la prioridad?"):
        st.markdown("""
Prioridad (0–100) = **40 %** rendimiento (100 − % aciertos; sin datos cuenta 50)
+ **20 %** repasos vencidos (sobre preguntas practicadas)
+ **20 %** parte del tema aún sin practicar
+ **10 %** días sin practicar (máximo 14)
+ **10 %** empeoramiento reciente (últimas 20 respuestas peor que tu media).
""")
    top = pr.iloc[0]
    st.info(f"Tema más prioritario: **{top['tema']} · {top['nombre']}** (prioridad {top['prioridad']:.0f}).")
    if st.button("Hacer un test de 20 preguntas de este tema"):
        from core import exams
        ids = exams.select_questions([top["topic_id"]], 20, exams.SEL_SMART)
        nav.start_exam("tema_aleatorio", "practica", f"Plan · {top['tema']}", ids, [top["topic_id"]])
