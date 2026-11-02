"""Test por temas: test originales y modalidades aleatorias."""
from __future__ import annotations

import streamlit as st

from core import bank, exams, srs, stats
from ui import nav
from ui.components import esc, kpi_row


def topic_selector(key: str, default: str | None = None, include_empty: bool = False) -> str | None:
    tps = bank.topics(include_empty=include_empty)
    if not tps:
        st.warning("No hay temas importados.")
        return None
    ids = [t["id"] for t in tps]
    default = default if default in ids else st.session_state.get(f"{key}_last", ids[0])
    tid = st.selectbox("Tema", ids, index=ids.index(default) if default in ids else 0,
                       format_func=lambda t: bank.topic_label(t), key=key)
    st.session_state[f"{key}_last"] = tid
    return tid


def render() -> None:
    nav.page_header("Hacer test por tema", "Test originales en su orden y prácticas aleatorias con preguntas reales del tema.", "📝")
    tid = topic_selector("tema_sel", st.session_state.pop("tema_topic", None))
    if not tid:
        return
    t = bank.topic(tid)
    ids = bank.question_ids_for_topics([tid])
    states = srs.all_states()
    seen = [i for i in ids if i in states and states[i]["n_seen"]]
    failed = [i for i in seen if states[i]["n_wrong"] > 0]
    df = stats.per_topic()
    row = df[df["topic_id"] == tid].iloc[0] if not df.empty and (df["topic_id"] == tid).any() else None
    st.caption(esc(t["title"]))
    kpi_row([("Preguntas", str(len(ids)), "verificadas"),
             ("Practicadas", str(len(seen)), f"{len(ids) - len(seen)} sin responder"),
             ("% aciertos", f"{row['pct']:.0f} %" if row is not None and row["pct"] == row["pct"] and row["pct"] is not None else "—", ""),
             ("Falladas", str(len(failed)), f"{row['dominadas'] if row is not None else 0} dominadas")])
    st.write("")
    mode = nav.mode_picker("tema_mode")
    tl = nav.timer_picker("tema_timer")
    label = bank.topic_label(tid, short=True)

    st.subheader("Test originales")
    tests = bank.tests_for_topic(tid)
    if not tests:
        st.caption("Este tema no tiene test originales en los documentos.")
    for tt in tests:
        qids = bank.test_question_ids(tt["id"])
        excluded = tt["n_questions"] - len(qids)
        with st.container(border=True):
            c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
            c1.markdown(f"**{esc(tt['name'])}**  \n{tt['n_questions']} preguntas en el documento · orden original"
                        + (f" · ⚠️ {excluded} excluida(s) por no tener solución verificable" if excluded else ""))
            if c2.button(f"Hacer test ({len(qids)})", key=f"orig_{tt['id']}", type="primary", width="stretch", disabled=not qids):
                nav.start_exam("tema_original", mode, tt["name"], qids, [tid], time_limit_s=tl,
                               extra={"test_id": tt["id"]})

    st.subheader("Práctica aleatoria")
    cols = st.columns(5)
    for c, k in zip(cols, [10, 20, 30, 50, None]):
        lbl = f"{k} preguntas" if k else f"Todas ({len(ids)})"
        if c.button(lbl, key=f"rnd_{k}", width="stretch"):
            sel = exams.select_questions([tid], k, exams.SEL_ALL)
            nav.start_exam("tema_aleatorio", mode, f"{label} · {len(sel)} aleatorias", sel, [tid], time_limit_s=tl)
    st.caption("Si el tema tiene menos preguntas de las pedidas, se usan todas las disponibles. Se priorizan las que llevas más tiempo sin ver.")

    c1, c2, c3 = st.columns(3)
    if c1.button(f"❌ Repetir preguntas falladas ({len(failed)})", width="stretch", disabled=not failed):
        sel = exams.select_questions([tid], None, exams.SEL_FAILED)
        nav.start_exam("fallos", mode, f"{label} · falladas", sel, [tid], time_limit_s=tl)
    n_new = len(ids) - len(seen)
    if c2.button(f"🆕 Nunca respondidas ({n_new})", width="stretch", disabled=not n_new):
        sel = exams.select_questions([tid], 30, exams.SEL_NEW)
        nav.start_exam("nuevas", mode, f"{label} · nuevas", sel, [tid], time_limit_s=tl)
    if c3.button("🧠 Mezcla inteligente (20)", width="stretch"):
        sel = exams.select_questions([tid], 20, exams.SEL_SMART)
        nav.start_exam("tema_aleatorio", mode, f"{label} · mezcla inteligente", sel, [tid], time_limit_s=tl)

    pend = [q for q in bank.pending_questions() if q.topic_id == tid]
    if pend:
        st.info(f"{len(pend)} pregunta(s) de este tema están pendientes de revisión y no se usan en test puntuables "
                "(ver «Banco y ajustes»).")
