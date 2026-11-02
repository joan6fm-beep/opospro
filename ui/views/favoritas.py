"""Preguntas favoritas y notas personales."""
from __future__ import annotations

import streamlit as st

from core import bank, db, userdata
from ui import nav
from ui.components import empty_state, question_view


def render() -> None:
    nav.page_header("Mis preguntas favoritas", "Marca preguntas con ☆ durante los test o desde cualquier listado.", "⭐")
    ids = userdata.favorite_ids()
    noted = [r[0] for r in db.query("SELECT question_id FROM notes ORDER BY updated_at DESC")]
    if not ids and not noted:
        empty_state("Aún no tienes favoritas. Pulsa «☆ Favorita» mientras haces un test.", "⭐")
        return
    tab1, tab2 = st.tabs([f"⭐ Favoritas ({len(ids)})", f"📝 Con nota personal ({len(noted)})"])
    with tab1:
        qs = bank.get_questions(ids)
        tids = sorted({q.topic_id for q in qs.values()})
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        tsel = c1.selectbox("Filtrar por tema", ["(todos)"] + tids, format_func=lambda t: t if t == "(todos)" else bank.topic_label(t))
        shown = [i for i in ids if i in qs and (tsel == "(todos)" or qs[i].topic_id == tsel)]
        practicable = [i for i in shown if qs[i].scoreable]
        mode = nav.mode_picker("fav_mode")
        if c2.button(f"▶ Practicar ({len(practicable)})", type="primary", width="stretch", disabled=not practicable):
            nav.start_exam("favoritas", mode, "Mis favoritas", practicable, shuffle=True)
        for i in shown:
            q = qs[i]
            with st.expander(f"{bank.topic_label(q.topic_id, short=True)} — {q.stem[:110]}"):
                question_view(q, None, key=f"fav_{i}")
    with tab2:
        qs = bank.get_questions(noted)
        for i in noted:
            if i in qs:
                with st.expander(f"📝 {qs[i].stem[:110]}"):
                    question_view(qs[i], None, key=f"note_{i}")
