"""Análisis y práctica de errores."""
from __future__ import annotations

from datetime import datetime, timedelta

import plotly.graph_objects as go
import streamlit as st

from core import bank, exams, srs, stats
from ui import nav, theme
from ui.components import empty_state, kpi_row, question_view


def render() -> None:
    nav.page_header("Mis fallos", "Cada pregunta fallada se guarda y se programa para repaso hasta que la domines.", "❌")
    df = stats.failed_questions_df()
    if df.empty:
        empty_state("Todavía no has fallado ninguna pregunta. Cuando falles alguna aparecerá aquí.", "🎉")
        return
    active = df[df["estado"] == "Fallada"]
    recovered = df[df["estado"].isin(["Recuperada"])]
    kpi_row([("Preguntas falladas", str(len(df)), "alguna vez"),
             ("Siguen falladas", str(len(active)), "último intento incorrecto"),
             ("En aprendizaje", str(int((df["estado"] == "Aprendiendo").sum())), "acertadas después"),
             ("Recuperadas", str(len(recovered)), "antes fallabas, ahora dominas")])
    st.write("")
    mode = nav.mode_picker("fa_mode")

    st.subheader("Practicar")
    c = st.columns(4)
    if c[0].button(f"🔁 Repetir todos mis fallos ({len(df)})", type="primary", width="stretch"):
        nav.start_exam("fallos", mode, "Todos mis fallos", exams.select_questions(None, None, exams.SEL_FAILED))
    if c[1].button("🔥 Las más falladas (20)", width="stretch"):
        ids = df.sort_values(["veces_fallada", "aciertos_posteriores"], ascending=[False, True])["question_id"].tolist()[:20]
        nav.start_exam("fallos", mode, "Mis preguntas más falladas", ids)
    since = (datetime.now() - timedelta(days=7)).isoformat()
    recent = df[df["ultimo_fallo"].fillna("") >= since]
    if c[2].button(f"🕑 Fallos recientes ({len(recent)})", width="stretch", disabled=recent.empty,
                   help="Fallados en los últimos 7 días"):
        nav.start_exam("fallos", mode, "Fallos de los últimos 7 días", recent["question_id"].tolist(), shuffle=True)
    topics_with = sorted(df["topic_id"].unique(), key=lambda t: bank.topic(t)["sort_order"] if bank.topic(t) else 999)
    with c[3].popover("📂 Fallos por tema", width="stretch"):
        tid = st.selectbox("Tema", topics_with, format_func=lambda t: bank.topic_label(t))
        n_t = int((df["topic_id"] == tid).sum())
        if st.button(f"Practicar {n_t} fallos", type="primary"):
            nav.start_exam("fallos", mode, f"Fallos · {bank.topic_label(tid, short=True)}",
                           exams.select_questions([tid], None, exams.SEL_FAILED), [tid])

    # gráfico: fallos por tema por estado
    g = df.groupby(["tema", "estado"]).size().unstack(fill_value=0)
    fig = go.Figure()
    for i, (estado, color) in enumerate([("Fallada", theme.CRITICAL), ("Aprendiendo", theme.SERIES[3]), ("Recuperada", theme.GOOD)]):
        if estado in g.columns:
            fig.add_bar(y=g.index, x=g[estado], name=estado, orientation="h", marker_color=color, marker_cornerradius=4,
                        marker_line=dict(color="#fcfcfb", width=2), hovertemplate="%{y}: %{x} " + estado.lower() + "s<extra></extra>")
    fig.update_layout(barmode="stack", title="Estado de tus fallos por tema", height=80 + 34 * len(g), legend=dict(y=-0.25))
    theme.chart(fig)

    st.subheader("Listado")
    f1, f2, f3 = st.columns([2, 1.5, 1.5])
    tsel = f1.selectbox("Tema", ["(todos)"] + list(topics_with), format_func=lambda t: t if t == "(todos)" else bank.topic_label(t), key="fa_t")
    est = f2.selectbox("Estado", ["(todos)", "Fallada", "Aprendiendo", "Recuperada"], key="fa_e")
    order = f3.selectbox("Ordenar por", ["Más falladas", "Más recientes"], key="fa_o")
    view = df.copy()
    if tsel != "(todos)":
        view = view[view["topic_id"] == tsel]
    if est != "(todos)":
        view = view[view["estado"] == est]
    view = view.sort_values("veces_fallada" if order == "Más falladas" else "ultimo_fallo", ascending=False)
    st.caption(f"{len(view)} preguntas")
    qs = bank.get_questions(view["question_id"].tolist()[:200])
    for _, r in view.head(200).iterrows():
        q = qs.get(r["question_id"])
        if not q:
            continue
        icon = {"Fallada": "🔴", "Aprendiendo": "🟡", "Recuperada": "🟢"}.get(r["estado"], "⚪")
        title = (f"{icon} {r['tema']} · fallada {r['veces_fallada']}× · {r['aciertos_posteriores']} aciertos después · "
                 f"última vez {str(r['ultima_vez'])[:10]} — {q.stem[:90]}…")
        with st.expander(title):
            st.caption(f"Estado: **{r['estado']}** · próximo repaso: {str(r['repaso'])[:10]}")
            question_view(q, None, key=f"fa_{q.id}")
