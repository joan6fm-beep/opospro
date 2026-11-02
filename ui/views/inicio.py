"""Panel principal."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import bank, exams, plan, srs, stats
from ui import nav, theme
from ui.components import esc, fmt_time, kpi_row


def _action(col, icon: str, title: str, desc: str, key: str, target: str, primary: bool = False):
    with col:
        st.markdown(f'<div class="action-card"><div class="ic">{icon}</div><div class="t">{title}</div>'
                    f'<div class="d">{desc}</div></div>', unsafe_allow_html=True)
        if st.button("Entrar", key=f"go_{key}", width="stretch", type="primary" if primary else "secondary"):
            nav.go(target)


def run_recommendation(r: plan.Recommendation) -> None:
    if r.action == "repaso":
        nav.start_exam("repaso", "practica", "Repaso inteligente de hoy", srs.due_ids()[:40])
    elif r.action == "fallos":
        ids = exams.select_questions(None, 30, exams.SEL_FAILED)
        nav.start_exam("fallos", "practica", "Test de preguntas falladas", ids)
    elif r.action == "nuevas_tema":
        ids = exams.select_questions([r.topic_id], 20, exams.SEL_NEW)
        nav.start_exam("nuevas", "practica", f"Preguntas nuevas · {bank.topic_label(r.topic_id, short=True)}", ids, [r.topic_id])
    elif r.action == "tema_test":
        ids = exams.select_questions([r.topic_id], 20, exams.SEL_SMART)
        nav.start_exam("tema_aleatorio", "practica", f"Repaso · {bank.topic_label(r.topic_id, short=True)}", ids, [r.topic_id])
    elif r.action == "estudiar_tema":
        nav.go("temario", temario_topic=r.topic_id)
    elif r.action == "resumen_errores":
        nav.go("resumenes", resumen_tipo="errores")
    else:
        nav.go("tema")


def render() -> None:
    ov = stats.overview()
    n_q = len(bank.question_ids_for_topics(None))
    st.markdown(f'<div class="hero"><h1>Auxiliar Administrativo · Tu plataforma de estudio</h1>'
                f'<p>{n_q} preguntas reales verificadas de tus documentos · Estudiar → Practicar → Corregir → Entender → Repasar → Mejorar</p></div>',
                unsafe_allow_html=True)

    opens = exams.open_exams()
    if opens:
        e = opens[0]
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.info(f"Tienes un examen sin terminar: **{e['title']}** (iniciado {e['started_at'][:16].replace('T', ' ')}).")
        if c2.button("▶ Continuar", type="primary", width="stretch"):
            st.session_state["exam_id"] = e["id"]
            st.session_state.pop("result_exam_id", None)
            nav.go("examen")

    c = st.columns(4)
    _action(c[0], "📝", "HACER TEST", "Elige un tema y sus test originales", "tema", "tema", True)
    _action(c[1], "🎲", "TEST ALEATORIO", "Mezcla preguntas reales de varios temas", "aleat", "aleatorio")
    n_fail = len(stats.failed_questions_df())
    _action(c[2], "❌", "REPASAR MIS FALLOS", f"{n_fail} preguntas falladas guardadas", "fallos", "fallos")
    _action(c[3], "📚", "ESTUDIAR TEMARIO", "Teoría, esquemas y resúmenes", "temario", "temario")

    st.write("")
    q = st.columns(5)
    for col, (lbl, key) in zip(q, [("⏱️ Simulacros", "simulacros"), ("📊 Estadísticas", "estadisticas"),
                                   ("⭐ Favoritas", "favoritas"), ("📈 Mi progreso", "progreso"), ("🗓️ Mi plan", "plan")]):
        if col.button(lbl, width="stretch", key=f"q_{key}"):
            nav.go(key)

    st.write("")
    kpi_row([
        ("Aciertos globales", f"{ov['pct']:.0f} %" if ov["pct"] is not None else "—", f"{ov['correct']} aciertos · {ov['wrong']} fallos"),
        ("Preguntas respondidas", str(ov["answered"]), f"{ov['distinct_seen']} distintas de {n_q}"),
        ("Test completados", str(ov["exams"]), f"nota media {ov['avg_grade']:.2f}" if ov["avg_grade"] is not None else "aún sin test"),
        ("Tiempo de estudio", fmt_time(ov["seconds"]), "test + temario"),
    ])
    st.write("")

    left, right = st.columns([1.35, 1])
    with left:
        with st.container(border=True):
            st.markdown("**Evolución reciente**")
            ev = stats.evolution()
            if ev is None or ev.empty:
                st.caption("Completa tu primer test para ver tu evolución.")
            else:
                ev = ev.tail(12)
                fig = go.Figure(go.Scatter(
                    x=[f"#{i}" for i in ev["n"]], y=ev["pct"], mode="lines+markers",
                    line=dict(color=theme.SERIES[0], width=2), marker=dict(size=8, color=theme.SERIES[0]),
                    customdata=ev[["title", "n_correct", "n_questions"]],
                    hovertemplate="%{customdata[0]}<br>%{y:.0f} % (%{customdata[1]}/%{customdata[2]})<extra></extra>"))
                fig.update_layout(height=220, yaxis=dict(range=[0, 100], ticksuffix=" %"), margin=dict(t=10, b=10, l=10, r=10),
                                  xaxis=dict(type="category", title=None))
                theme.chart(fig)
        best, worst = stats.best_worst_topics()
        b1, b2 = st.columns(2)
        with b1, st.container(border=True):
            st.markdown("🏆 **Mejor tema**")
            if best:
                st.markdown(f"{esc(best['tema'])} · {esc(best['nombre'])}  \n**{best['pct']:.0f} %** en {int(best['respuestas'])} respuestas")
            else:
                st.caption("Responde al menos 5 preguntas de un tema.")
        with b2, st.container(border=True):
            st.markdown("⚠️ **Tema a reforzar**")
            if worst and best and worst["topic_id"] != best["topic_id"]:
                st.markdown(f"{esc(worst['tema'])} · {esc(worst['nombre'])}  \n**{worst['pct']:.0f} %** en {int(worst['respuestas'])} respuestas")
            else:
                st.caption("Necesitas datos de al menos dos temas.")
    with right:
        with st.container(border=True):
            due = srs.due_ids()
            st.markdown("🔁 **Próximo repaso recomendado**")
            if due:
                st.markdown(f"Tienes **{len(due)}** preguntas pendientes de repaso hoy.")
                if st.button("Empezar repaso", type="primary", width="stretch"):
                    nav.start_exam("repaso", "practica", "Repaso inteligente de hoy", due[:40])
            else:
                st.caption("No hay repasos pendientes hoy. ¡Buen trabajo!")
        with st.container(border=True):
            st.markdown("🗓️ **Hoy te recomendamos**")
            for i, r in enumerate(plan.recommendations(3)):
                st.markdown(f"{r.icon} **{esc(r.title)}**  \n<span style='color:#52514e;font-size:.9rem'>{esc(r.reason)}</span>",
                            unsafe_allow_html=True)
                if st.button("Hacerlo ahora", key=f"rec_{i}", width="stretch"):
                    run_recommendation(r)
