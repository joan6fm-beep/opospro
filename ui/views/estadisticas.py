"""Estadísticas personales y progreso por tema."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import bank, exams, srs, stats
from ui import nav, theme
from ui.components import empty_state, fmt_time, kpi_row

CFG = {"displayModeBar": False}


def _evolution():
    ev = stats.evolution()
    if ev is None or ev.empty:
        return None
    fig = go.Figure()
    xs = [f"#{n}" for n in ev["n"]]
    fig.add_scatter(x=xs, y=ev["pct"], mode="lines+markers", name="% aciertos",
                    line=dict(color=theme.SERIES[0], width=2), marker=dict(size=8),
                    customdata=ev[["title", "nota", "finished_at"]],
                    hovertemplate="%{customdata[0]}<br>%{customdata[2]|%d/%m %H:%M}<br>%{y:.0f} % · nota %{customdata[1]:.2f}<extra></extra>")
    if len(ev) >= 3:
        roll = ev["pct"].rolling(3, min_periods=1).mean()
        fig.add_scatter(x=xs, y=roll, mode="lines", name="Media móvil (3)",
                        line=dict(color=theme.SERIES[1], width=2, dash="dot"), hovertemplate="Media: %{y:.0f} %<extra></extra>")
    fig.update_layout(title="Evolución de aciertos por examen", height=320, yaxis=dict(range=[0, 100], ticksuffix=" %"),
                      xaxis=dict(type="category"))
    return fig


def _topics_bar(df):
    d = df[df["respuestas"] > 0].sort_values("pct")
    if d.empty:
        return None
    colors = [theme.BLUE_SEQ[min(6, 1 + int(p // 17))] for p in d["pct"]]
    fig = go.Figure(go.Bar(y=d["tema"], x=d["pct"], orientation="h", marker_color=colors, marker_cornerradius=4,
                           text=[f"{p:.0f} %" for p in d["pct"]], textposition="outside", textfont=dict(color=theme.INK2),
                           customdata=d[["nombre", "respuestas"]],
                           hovertemplate="%{y} · %{customdata[0]}<br>%{x:.0f} % en %{customdata[1]} respuestas<extra></extra>"))
    fig.update_layout(title="Comparativa de rendimiento por tema", height=90 + 34 * len(d), xaxis=dict(range=[0, 110], ticksuffix=" %"))
    return fig


def _mastery(df):
    if df.empty:
        return None
    fig = go.Figure()
    p = srs.params()
    states = srs.all_states()
    rows = []
    for _, r in df.iterrows():
        ids = bank.question_ids_for_topics([r["topic_id"]])
        c = {"Dominadas": 0, "Aprendiendo": 0, "Falladas": 0, "Nuevas": 0}
        for i in ids:
            s = states.get(i)
            if not s or not s["n_seen"]:
                c["Nuevas"] += 1
            elif s["box"] >= p["mastery_box"]:
                c["Dominadas"] += 1
            elif s["last_result"] == 0:
                c["Falladas"] += 1
            else:
                c["Aprendiendo"] += 1
        rows.append((r["tema"], c))
    for name, color in [("Dominadas", theme.GOOD), ("Aprendiendo", theme.SERIES[0]), ("Falladas", theme.CRITICAL), ("Nuevas", "#d9d8d2")]:
        fig.add_bar(y=[t for t, _ in rows], x=[c[name] for _, c in rows], name=name, orientation="h", marker_color=color,
                    marker_line=dict(color="#fcfcfb", width=2), hovertemplate="%{y}: %{x} " + name.lower() + "<extra></extra>")
    fig.update_layout(barmode="stack", title="Preguntas dominadas por tema", height=110 + 34 * len(rows), legend=dict(y=-0.2))
    return fig


def render() -> None:
    nav.page_header("Mis estadísticas", "Todo calculado a partir de tus respuestas guardadas.", "📊")
    ov = stats.overview()
    if not ov["answered"]:
        empty_state("Aún no hay respuestas. Haz tu primer test para ver estadísticas.", "📊")
        return
    kpi_row([("Exámenes", str(ov["exams"]), "finalizados"), ("Respondidas", str(ov["answered"]), f"{ov['distinct_seen']} distintas"),
             ("Aciertos", str(ov["correct"]), f"{ov['pct']:.0f} %"), ("Fallos", str(ov["wrong"]), ""),
             ("En blanco", str(ov["blank"]), ""), ("Nota media", f"{ov['avg_grade']:.2f}" if ov["avg_grade"] is not None else "—", "sobre 10"),
             ("Tiempo", fmt_time(ov["seconds"]), "")])
    st.write("")
    df = stats.per_topic()
    t1, t2, t3 = st.tabs(["📈 General", "📚 Por tema", "⏱️ Tiempo y simulacros"])
    with t1:
        f = _evolution()
        if f:
            theme.chart(f)
        c1, c2 = st.columns(2)
        with c1:
            f = _topics_bar(df)
            if f:
                theme.chart(f)
        with c2:
            ed = stats.error_distribution()
            if not ed.empty:
                ed = ed.sort_values("fallos")
                fig = go.Figure(go.Bar(y=ed["tema"], x=ed["fallos"], orientation="h", marker_color=theme.CRITICAL,
                                       marker_cornerradius=4, hovertemplate="%{y}: %{x} fallos<extra></extra>",
                                       text=ed["fallos"], textposition="outside", textfont=dict(color=theme.INK2)))
                fig.update_layout(title="Distribución de errores (respuestas falladas)", height=90 + 34 * len(ed))
                theme.chart(fig)
    with t2:
        f = _mastery(df)
        if f:
            theme.chart(f)
        show = df[["tema", "nombre", "disponibles", "practicadas", "pct", "fallos", "dominadas", "pendientes_repaso"]].copy()
        st.dataframe(show, hide_index=True, column_config={
            "tema": "Tema", "nombre": "Contenido", "disponibles": "Disponibles", "practicadas": "Practicadas",
            "pct": st.column_config.ProgressColumn("% aciertos", min_value=0, max_value=100, format="%.0f %%"),
            "fallos": "Fallos", "dominadas": "Dominadas", "pendientes_repaso": "Repaso pendiente"})
        tid = st.selectbox("Evolución de un tema", df["topic_id"].tolist(), format_func=lambda t: bank.topic_label(t))
        a = stats.answers_df()
        a = a[a["answered"] & a["question_id"].isin(set(bank.question_ids_for_topics([tid])))]
        if a.empty:
            st.caption("Sin respuestas en este tema.")
        else:
            g = a.groupby("day").agg(n=("ok", "size"), ok=("ok", "sum")).reset_index()
            g["pct"] = g["ok"] / g["n"] * 100
            fig = go.Figure(go.Scatter(x=g["day"], y=g["pct"], mode="lines+markers", line=dict(color=theme.SERIES[0], width=2),
                                       marker=dict(size=8), customdata=g[["ok", "n"]],
                                       hovertemplate="%{x}: %{y:.0f} % (%{customdata[0]}/%{customdata[1]})<extra></extra>"))
            fig.update_layout(title=f"Rendimiento diario · {bank.topic_label(tid, short=True)}", height=280,
                              yaxis=dict(range=[0, 105], ticksuffix=" %"))
            theme.chart(fig)
    with t3:
        td = stats.study_time_by_day(30)
        if not td.empty:
            fig = go.Figure()
            for i, tipo in enumerate(["Test", "Temario"]):
                d = td[td["tipo"] == tipo]
                fig.add_bar(x=d["day"], y=d["minutos"], name=tipo, marker_color=theme.SERIES[i],
                            marker_line=dict(color="#fcfcfb", width=2), hovertemplate="%{x}: %{y} min " + tipo.lower() + "<extra></extra>")
            fig.update_layout(barmode="stack", title="Tiempo de estudio (últimos 30 días, minutos)", height=300)
            theme.chart(fig)
        sims = exams.history(kind="simulacro")[:10][::-1]
        if sims:
            fig = go.Figure(go.Bar(x=[s["finished_at"][:10] + f" #{s['id']}" for s in sims], y=[s["grade"] for s in sims],
                                   marker_color=[theme.GOOD if s["grade"] >= 5 else theme.CRITICAL for s in sims], marker_cornerradius=4,
                                   text=[f"{s['grade']:.2f}" for s in sims], textposition="outside",
                                   hovertemplate="%{x}: nota %{y:.2f}<extra></extra>"))
            fig.update_layout(title="Últimos simulacros (verde ≥ 5 · rojo < 5)", height=300, yaxis=dict(range=[0, 10.8]))
            theme.chart(fig)
        else:
            st.caption("Aún no has hecho simulacros.")


def render_progress() -> None:
    nav.page_header("Mi progreso", "Cuánto del banco de preguntas has trabajado y dominado.", "📈")
    df = stats.per_topic()
    p = srs.params()
    total = int(df["disponibles"].sum()) if not df.empty else 0
    mastered = int(df["dominadas"].sum()) if not df.empty else 0
    practiced = int(df["practicadas"].sum()) if not df.empty else 0
    kpi_row([("Banco total", str(total), "preguntas verificadas"), ("Practicadas", str(practiced), f"{practiced / total * 100:.0f} %" if total else ""),
             ("Dominadas", str(mastered), f"{mastered / total * 100:.0f} %" if total else ""),
             ("Repasos pendientes", str(len(srs.due_ids())), "hoy")])
    st.write("")
    for _, r in df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 3, 1.2], vertical_alignment="center")
            c1.markdown(f"**{r['tema']}** · {r['nombre']}")
            frac = r["dominadas"] / r["disponibles"] if r["disponibles"] else 0
            c2.progress(frac, text=f"{r['dominadas']}/{r['disponibles']} dominadas · {r['practicadas']} practicadas"
                        + (f" · {r['pct']:.0f} % aciertos" if r["pct"] == r["pct"] and r["pct"] is not None else ""))
            if c3.button("Practicar", key=f"pp_{r['topic_id']}", width="stretch"):
                nav.go("tema", tema_topic=r["topic_id"])
    f = _mastery(df)
    if f:
        theme.chart(f)
    st.caption(f"Una pregunta se considera dominada al alcanzar la caja {p['mastery_box']} del sistema de repaso "
               "(ver «Banco y ajustes» para los criterios).")
