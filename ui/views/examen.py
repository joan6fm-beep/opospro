"""Pantalla de examen: responder, navegar, cronómetro, finalizar, resultados y recuperación."""
from __future__ import annotations

import time

import plotly.graph_objects as go
import streamlit as st

from core import bank, exams, userdata
from core.extract.test_parser import LETTERS
from ui import nav, theme
from ui.components import esc, explanation_panel, fmt_time, kpi_row, review_list, empty_state

IDLE_CAP = 300  # en exámenes sin límite, un hueco >5 min sin actividad no cuenta como estudio


# ------------------------------------------------------------------ tiempo

def _tick(eid: int, timed: bool) -> None:
    now = time.time()
    last = st.session_state.get("_tick")
    if last and st.session_state.get("_tick_exam") == eid:
        delta = now - last
        exams.add_elapsed(eid, int(delta if timed else min(delta, IDLE_CAP)))
        # conserva la fracción de segundo para no perder tiempo por redondeo
        st.session_state["_tick"] = now - (delta - int(delta))
    else:
        st.session_state["_tick"] = now
    st.session_state["_tick_exam"] = eid


def _finish(eid: int) -> None:
    e = exams.get_exam(eid)
    _tick(eid, bool(e["time_limit_s"]))
    exams.finish(eid)
    st.session_state["result_exam_id"] = eid
    st.session_state.pop("exam_id", None)
    st.session_state.pop("_tick", None)


_TIMER_JS = """<div id="t" style="font:750 1.05rem system-ui,-apple-system,Segoe UI,sans-serif;font-variant-numeric:tabular-nums;
padding:4px 12px;border-radius:999px;display:inline-block;background:#eef2f8;color:#184f95"></div>
<script>
const down = %(down)s; let v = %(start)s; const t0 = Date.now(); const el = document.getElementById("t");
function draw() {
  const x = Math.max(0, down ? v - Math.floor((Date.now() - t0) / 1000) : v + Math.floor((Date.now() - t0) / 1000));
  el.textContent = "⏱ " + String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x %% 60).padStart(2, "0");
  if (down && x < 120) { el.style.background = "#fde8e8"; el.style.color = "#a32020"; }
}
draw(); setInterval(draw, 1000);
</script>"""


# El reloj cuenta en el navegador (sin pedir nada al servidor cada segundo, clave con datos móviles);
# el servidor solo comprueba cada 20 s si se agotó el tiempo.
@st.fragment(run_every=20)
def _clock(eid: int, limit: int | None, base_elapsed: int, tick_start: float) -> None:
    elapsed = base_elapsed + (time.time() - tick_start)
    if limit and limit - elapsed <= 0:
        _finish(eid)
        st.toast("⏰ Tiempo agotado: examen finalizado")
        st.rerun(scope="app")
    start = int(limit - elapsed) if limit else int(elapsed)
    st.iframe(_TIMER_JS % {"down": "true" if limit else "false", "start": start}, height=38, width=140)


# ------------------------------------------------------------------ acciones (callbacks)

def _choose(eid, pos, letter):
    exams.answer(eid, pos, letter)


def _goto(eid, pos):
    exams.set_position(eid, pos)


def _blank_next(eid, pos, n):
    e = exams.get_exam(eid)
    if e["mode"] == "examen":
        exams.answer(eid, pos, None)
    exams.set_position(eid, min(pos + 1, n - 1))


def _flag(eid, pos, val):
    exams.set_flag(eid, pos, val)


def _close_confirm():
    st.session_state.pop("confirm_finish", None)


@st.dialog("¿Finalizar el examen?", on_dismiss=_close_confirm)
def _confirm_finish(eid: int, answers: list[dict]) -> None:
    blank = sum(1 for a in answers if a["selected"] is None)
    flagged = sum(1 for a in answers if a["flagged"])
    st.write(f"Has respondido **{len(answers) - blank} de {len(answers)}** preguntas.")
    if blank:
        st.warning(f"Quedan **{blank}** preguntas sin responder (contarán como en blanco).")
    if flagged:
        st.info(f"Tienes **{flagged}** preguntas marcadas para revisar.")
    c1, c2 = st.columns(2)
    if c1.button("Seguir respondiendo", width="stretch"):
        _close_confirm()
        st.rerun()
    if c2.button("Finalizar y corregir", type="primary", width="stretch"):
        _close_confirm()
        _finish(eid)
        st.rerun()


# ------------------------------------------------------------------ pantalla

def _resume_list() -> None:
    nav.page_header("Examen en curso", "Aquí se recuperan los exámenes que no llegaste a finalizar.", "▶️")
    opens = exams.open_exams()
    if not opens:
        empty_state("No tienes ningún examen en curso. Empieza uno desde «Hacer test», «Test aleatorio» o «Simulacros».", "✅")
        if st.button("Ir a Hacer test", type="primary"):
            nav.go("tema")
        return
    for e in opens:
        ans = exams.get_answers(e["id"])
        done = sum(1 for a in ans if a["selected"] is not None)
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 1.4, 1.2], vertical_alignment="center")
            c1.markdown(f"**{esc(e['title'])}**  \n{exams.KIND_LABELS.get(e['kind'], e['kind'])} · "
                        f"{'Práctica' if e['mode'] == 'practica' else 'Examen'} · iniciado {e['started_at'][:16].replace('T', ' ')} · "
                        f"{done}/{len(ans)} respondidas · {fmt_time(e['elapsed_s'])}")
            if c2.button("▶ Continuar", key=f"res_{e['id']}", type="primary", width="stretch"):
                st.session_state["exam_id"] = e["id"]
                st.session_state.pop("_tick", None)
                st.rerun()
            if c3.button("Descartar", key=f"abn_{e['id']}", width="stretch"):
                exams.abandon(e["id"])
                st.rerun()


def _results(eid: int) -> None:
    e = exams.get_exam(eid)
    answers = exams.get_answers(eid)
    res = exams.compute_result(answers, e["config"]["scoring"])
    sc = e["config"]["scoring"]
    nav.page_header("Resultado", esc(e["title"]), "🏁")
    color = theme.GOOD if res.grade >= 5 else theme.CRITICAL
    st.markdown(f'<div class="card" style="text-align:center"><div class="kpi"><div class="lbl">Nota</div>'
                f'<div class="val" style="font-size:3rem;color:{color}">{res.grade:.2f}<span style="font-size:1.2rem;color:#898781"> / {sc.get("scale", 10):g}</span></div>'
                f'<div class="sub">{"✅ Aprobado" if res.grade >= sc.get("scale", 10) / 2 else "❌ Por debajo de la mitad"} · '
                f'{res.score:g} puntos de {res.max_score:g}</div></div></div>', unsafe_allow_html=True)
    st.write("")
    kpi_row([("Aciertos", str(res.correct), f"+{sc['correct']:g} c/u"),
             ("Errores", str(res.wrong), f"−{sc['wrong']:g} c/u" if sc["wrong"] else "sin penalización"),
             ("En blanco", str(res.blank), f"{sc.get('blank', 0):g} c/u"),
             ("% acierto", f"{res.pct:.0f} %", f"{res.n} preguntas"),
             ("Tiempo", fmt_time(e["elapsed_s"]), "")])
    if e["kind"] == "simulacro":
        st.caption("Simulación con parámetros configurables: no son criterios oficiales de corrección salvo que los hayas "
                   "ajustado a las bases de tu convocatoria.")
        prev = [h for h in exams.history(kind="simulacro") if h["id"] != eid][:9][::-1]
        if prev:
            xs = [f"#{h['id']}" for h in prev] + ["Este"]
            ys = [h["grade"] for h in prev] + [res.grade]
            fig = go.Figure(go.Bar(x=xs, y=ys, marker_color=[theme.BLUE_SEQ[2]] * len(prev) + [theme.SERIES[0]],
                                   hovertemplate="%{x}: nota %{y:.2f}<extra></extra>", marker_cornerradius=4))
            fig.update_layout(title="Comparación con simulacros anteriores", height=260, yaxis_range=[0, sc.get("scale", 10)])
            theme.chart(fig)
    c1, c2, c3 = st.columns(3)
    wrong_ids = [a["question_id"] for a in answers if a["selected"] is not None and not a["is_correct"]]
    if wrong_ids and c1.button(f"🔁 Repetir mis {len(wrong_ids)} fallos", type="primary", width="stretch"):
        nav.start_exam("fallos", "practica", f"Fallos de: {e['title']}", wrong_ids, e["topics"])
    if c2.button("🏠 Volver al inicio", width="stretch"):
        st.session_state.pop("result_exam_id", None)
        nav.go("inicio")
    if c3.button("📜 Ver historial", width="stretch"):
        st.session_state.pop("result_exam_id", None)
        nav.go("historial")
    st.subheader("Revisión completa")
    review_list(answers, key=f"rev{eid}")


def render() -> None:
    if st.session_state.get("result_exam_id"):
        _results(st.session_state["result_exam_id"])
        return
    eid = st.session_state.get("exam_id")
    e = exams.get_exam(eid) if eid else None
    if not e or e["status"] != "en_curso":
        st.session_state.pop("exam_id", None)
        _resume_list()
        return

    timed = bool(e["time_limit_s"])
    _tick(eid, timed)
    e = exams.get_exam(eid)
    answers = exams.get_answers(eid)
    n = len(answers)
    pos = min(max(e["current_index"] or 0, 0), n - 1)
    a = answers[pos]
    practice = e["mode"] == "practica"
    answered = sum(1 for x in answers if x["selected"] is not None)

    # cabecera
    c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
    c1.markdown(f"**{esc(e['title'])}** · {'🎯 Práctica' if practice else '📝 Examen'}")
    with c2:
        _clock(eid, e["time_limit_s"], int(e["elapsed_s"] or 0), st.session_state["_tick"])
    st.progress(answered / n, text=f"{answered} de {n} respondidas")

    q = bank.get_question(a["question_id"])
    with st.container(border=True):
        st.markdown(f'<div class="q-head"><span class="q-num">PREGUNTA {pos + 1} DE {n}</span>'
                    f'<span class="topic-chip">{esc(bank.topic_label(a["topic_id"], short=True))}</span></div>'
                    f'<div class="q-stem">{esc(a["stem"])}</div>', unsafe_allow_html=True)
        locked = practice and a["selected"] is not None
        for i, opt in enumerate(a["options"]):
            L = LETTERS[i]
            if locked:
                state = "ok" if L == a["correct_letter"] else ("ko" if L == a["selected"] else "dim")
            else:
                state = "sel" if L == a["selected"] else "n"
            with st.container(key=f"opt_{state}_{eid}_{pos}_{i}"):
                st.button(f"**{L.upper()})**  {opt}", key=f"b_{eid}_{pos}_{i}", width="stretch",
                          on_click=None if locked else _choose, args=(eid, pos, L), disabled=False)
        if locked and q:
            explanation_panel(q, a["selected"], key=f"{eid}_{pos}", options=a["options"],
                              correct_letter=a["correct_letter"], justification=a["justification"])

    # navegación
    b = st.columns([1, 1, 1, 1, 1])
    b[0].button("← Anterior", disabled=pos == 0, on_click=_goto, args=(eid, pos - 1), width="stretch")
    b[1].button("Siguiente →", disabled=pos >= n - 1, on_click=_goto, args=(eid, pos + 1), width="stretch", type="primary")
    b[2].button("Dejar sin responder", on_click=_blank_next, args=(eid, pos, n), width="stretch",
                disabled=practice and a["selected"] is not None, help="Deja la pregunta en blanco y pasa a la siguiente")
    b[3].button("⚑ Quitar marca" if a["flagged"] else "⚑ Marcar para revisar", on_click=_flag,
                args=(eid, pos, not a["flagged"]), width="stretch")
    fav = userdata.is_favorite(a["question_id"])
    if b[4].button("★ Favorita" if fav else "☆ Favorita", width="stretch"):
        userdata.toggle_favorite(a["question_id"])
        st.rerun()

    # el mapa (un botón por pregunta) solo se dibuja al abrirlo: con 100 preguntas aligera mucho cada recarga
    if st.toggle(f"🗺️ Mapa de preguntas ({answered}/{n} respondidas, {sum(x['flagged'] for x in answers)} marcadas)",
                 key=f"map_open_{eid}"):
        per_row = 10
        for r0 in range(0, n, per_row):
            cols = st.columns(per_row)
            for j, x in enumerate(answers[r0:r0 + per_row]):
                i = r0 + j
                if i == pos:
                    st_ = "cur"
                elif x["flagged"]:
                    st_ = "flag"
                elif x["selected"] is not None:
                    st_ = ("ok" if x["is_correct"] else "ko") if practice else "ans"
                else:
                    st_ = "n"
                with cols[j].container(key=f"map_{st_}_{eid}_{i}"):
                    st.button(str(i + 1), key=f"m_{eid}_{i}", on_click=_goto, args=(eid, i), width="stretch")
        st.caption("Azul: respondida · Amarillo: marcada · Verde/rojo: acierto/fallo (modo práctica) · Borde negro: actual")

    st.write("")
    c1, c2, _ = st.columns([1.3, 1.3, 2])
    if c1.button("🏁 Finalizar examen", type="primary", width="stretch"):
        st.session_state["confirm_finish"] = eid
    if st.session_state.get("confirm_finish") == eid:
        _confirm_finish(eid, answers)
    if c2.button("⏸ Pausar y salir", width="stretch", help="El examen queda guardado; podrás continuarlo después."):
        st.session_state.pop("exam_id", None)
        st.session_state.pop("_tick", None)
        nav.go("inicio")
