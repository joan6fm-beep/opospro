"""Estilo visual: CSS global y plantilla de gráficos Plotly (paleta validada para daltonismo)."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Paleta categórica (orden fijo, nunca ciclado) y colores de estado (siempre con icono + texto)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
WARNING = "#fab219"
NEUTRAL = "#c3c2b7"
BLUE_SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

CSS = """
<style>
:root { --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --surface:#ffffff; --plane:#f9f9f7;
        --brand:#2a78d6; --brand-dark:#184f95; --good:#0ca30c; --good-text:#006300; --bad:#d03b3b;
        --warn:#fab219; --ring:rgba(11,11,11,0.10); --radius:14px; }
html, body, [class*="css"] { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1180px; }
h1, h2, h3 { letter-spacing: -0.01em; }

/* ---------- cabecera ---------- */
.hero { background: linear-gradient(120deg, #184f95 0%, #2a78d6 60%, #3987e5 100%); color: #fff;
        border-radius: 18px; padding: 22px 26px; margin-bottom: 18px; box-shadow: 0 6px 24px rgba(24,79,149,.18); }
.hero h1 { color:#fff; font-size: 1.65rem; margin: 0 0 4px 0; }
.hero p { color: rgba(255,255,255,.88); margin: 0; font-size: .98rem; }
.page-title { font-size: 1.55rem; font-weight: 700; margin: 0 0 2px 0; }
.page-sub { color: var(--ink2); margin-bottom: 16px; }

/* ---------- tarjetas ---------- */
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: var(--radius);
        padding: 16px 18px; box-shadow: 0 1px 2px rgba(0,0,0,.03); height: 100%; }
.kpi { background: var(--surface); border: 1px solid var(--ring); border-radius: var(--radius); padding: 14px 16px; }
.kpi .lbl { color: var(--ink2); font-size: .82rem; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }
.kpi .val { font-size: 1.85rem; font-weight: 750; color: var(--ink); line-height: 1.15; margin-top: 2px; }
.kpi .sub { color: var(--muted); font-size: .82rem; }
.action-card { border-radius: 16px; padding: 18px 18px 10px 18px; color: var(--ink); border: 1px solid var(--ring);
               background: var(--surface); min-height: 152px; }
.action-card .ic { font-size: 1.7rem; }
.action-card .t { font-weight: 750; font-size: 1.08rem; margin-top: 4px; letter-spacing: .02em; }
.action-card .d { color: var(--ink2); font-size: .9rem; margin-top: 2px; }
.topic-chip { display:inline-block; background:#eef2f8; color:#184f95; border-radius: 999px; padding: 2px 10px;
              font-size: .78rem; font-weight: 650; margin-right: 6px; }
.badge { display:inline-block; border-radius: 6px; padding: 1px 8px; font-size: .72rem; font-weight: 750;
         letter-spacing:.04em; text-transform: uppercase; vertical-align: middle; margin-right: 6px; }
.b-oficial { background:#e3f5e3; color:#006300; border:1px solid #b9e3b9; }
.b-temario { background:#e6effb; color:#184f95; border:1px solid #c4d8f3; }
.b-ia { background:#eeeafb; color:#4a3aa7; border:1px solid #d5cdf5; }
.b-extracto { background:#f3f2ee; color:#52514e; border:1px solid #e1e0d9; }
.b-pend { background:#fff4dc; color:#7a5200; border:1px solid #f5dca0; }

/* ---------- examen ---------- */
.q-head { display:flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.q-num { font-weight: 800; font-size: .95rem; letter-spacing: .06em; color: var(--brand-dark); }
.q-stem { font-size: 1.16rem; line-height: 1.55; font-weight: 560; margin: 10px 0 14px 0; color: var(--ink); }
.timer { font-variant-numeric: tabular-nums; font-weight: 750; font-size: 1.05rem; padding: 4px 12px;
         border-radius: 999px; background:#eef2f8; color:#184f95; display:inline-block; }
.timer.low { background:#fde8e8; color:#a32020; }

/* botones de opción grandes, texto alineado a la izquierda */
[class*="st-key-opt_"] button { width: 100%; justify-content: flex-start; text-align: left; min-height: 3.1rem;
    padding: 10px 16px; border-radius: 12px; font-size: 1.0rem; white-space: normal; height: auto;
    border: 1.5px solid #d9dce3; background: #fff; color: var(--ink); }
[class*="st-key-opt_"] button > div, [class*="st-key-opt_"] button [data-testid="stMarkdownContainer"] {
    justify-content: flex-start !important; text-align: left !important; width: 100%; }
[class*="st-key-opt_"] button p { text-align: left !important; }
[class*="st-key-opt_"] button:hover { border-color: var(--brand); background: #f3f8fe; color: var(--ink); }
[class*="st-key-opt_sel_"] button, [class*="st-key-opt_sel_"] button:focus, [class*="st-key-opt_sel_"] button:hover { border-color: var(--brand) !important; background: #e6effb !important; box-shadow: inset 0 0 0 1px var(--brand); }
[class*="st-key-opt_ok_"] button, [class*="st-key-opt_ok_"] button:focus, [class*="st-key-opt_ok_"] button:hover { border-color: var(--good) !important; background: #e3f5e3 !important; box-shadow: inset 0 0 0 1px var(--good); }
[class*="st-key-opt_ko_"] button, [class*="st-key-opt_ko_"] button:focus, [class*="st-key-opt_ko_"] button:hover { border-color: var(--bad) !important; background: #fde8e8 !important; box-shadow: inset 0 0 0 1px var(--bad); }
[class*="st-key-opt_dim_"] button { opacity: .72; }

/* mapa de preguntas */
[class*="st-key-map_"] button { min-height: 2.1rem; padding: 0 4px; border-radius: 8px; font-size: .85rem; }
[class*="st-key-map_ans_"] button { background:#e6effb; border-color:#9ec5f4; }
[class*="st-key-map_ok_"] button { background:#e3f5e3; border-color:#9fd89f; }
[class*="st-key-map_ko_"] button { background:#fde8e8; border-color:#f0a8a8; }
[class*="st-key-map_flag_"] button { background:#fff4dc; border-color:#f5c451; }
[class*="st-key-map_cur_"] button { border: 2px solid #0b0b0b; font-weight: 800; }

/* bloques de explicación */
.exp { border-radius: 12px; padding: 12px 14px; margin: 8px 0; border: 1px solid var(--ring); background: #fff; }
.exp h4 { margin: 0 0 6px 0; font-size: .82rem; letter-spacing: .06em; text-transform: uppercase; color: var(--ink2); }
.exp.yours { border-left: 5px solid var(--bad); background:#fffafa; }
.exp.correct { border-left: 5px solid var(--good); background:#fafffa; }
.exp.why { border-left: 5px solid #6250d6; }
.exp.theory { border-left: 5px solid var(--brand); background:#fbfdff; }
.exp.remember { border-left: 5px solid var(--warn); background:#fffcf3; }
.exp.source { border-left: 5px solid var(--muted); font-size: .9rem; color: var(--ink2); }
.quote { font-family: Georgia, "Times New Roman", serif; font-size: .98rem; color:#262626; line-height:1.55; }
.res-ok { background:#e3f5e3; color:#006300; border-radius: 10px; padding: 10px 14px; font-weight: 700; }
.res-ko { background:#fde8e8; color:#8f1d1d; border-radius: 10px; padding: 10px 14px; font-weight: 700; }

/* temario */
.theory-p { line-height: 1.65; font-size: 1.0rem; margin: 0 0 10px 0; }
.sec-title { font-weight: 750; margin-top: 10px; }
.pg { color: var(--muted); font-size: .78rem; }

/* botones primarios más grandes */
.stButton > button[kind="primary"] { font-weight: 700; }
div[data-testid="stMetricValue"] { font-weight: 750; }

@media (max-width: 640px) {
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: 3.4rem; }
  .hero { padding: 16px; } .hero h1 { font-size: 1.3rem; }
  .q-stem { font-size: 1.05rem; }
  .kpi .val { font-size: 1.45rem; }
  /* móvil: zonas táctiles grandes y botones a todo el ancho */
  .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button { width: 100%; min-height: 2.9rem; }
  div[role="radiogroup"] label { padding: .55rem .2rem; min-height: 2.6rem; }
  div[role="radiogroup"] label p { font-size: 1rem; }
  div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .5rem; }
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] { min-width: calc(50% - .5rem); }
}
</style>
"""


SIDEBAR_CSS = """<style>
[data-testid="stSidebarContent"]{display:flex;flex-direction:column}
[data-testid="stSidebarUserContent"]{order:-1;padding-top:.5rem;padding-bottom:0}
</style>"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(SIDEBAR_CSS, unsafe_allow_html=True)  # estado de sincronización arriba, antes del menú


def plotly_template() -> None:
    if pio.templates.default == "opos":  # ya registrada en este proceso
        return
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK2, size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        xaxis=dict(gridcolor=GRID, linecolor=NEUTRAL, zeroline=False, tickfont=dict(color=MUTED), automargin=True),
        yaxis=dict(gridcolor=GRID, linecolor=NEUTRAL, zeroline=False, tickfont=dict(color=INK2), automargin=True),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(bgcolor="#ffffff", font=dict(color=INK), bordercolor=GRID),
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(color=INK2)),
        title=dict(font=dict(color=INK, size=15), x=0, xanchor="left"),
        bargap=0.35,
    )
    pio.templates["opos"] = t
    pio.templates.default = "opos"


def chart(fig: go.Figure) -> None:
    """Muestra un gráfico con el estilo de la app (plantilla aplicada explícitamente)."""
    if "opos" not in pio.templates:
        plotly_template()
    fig.update_layout(template=pio.templates["opos"], plot_bgcolor=SURFACE, paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False, "responsive": True})
