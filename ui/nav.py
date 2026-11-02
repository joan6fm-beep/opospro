"""Registro de páginas y acciones de navegación compartidas."""
from __future__ import annotations

import streamlit as st

from core import exams

PAGES: dict[str, st.Page] = {}


def register(key: str, page: st.Page) -> st.Page:
    PAGES[key] = page
    return page


def go(key: str, **state) -> None:
    for k, v in state.items():
        st.session_state[k] = v
    st.switch_page(PAGES[key])


def start_exam(kind: str, mode: str, title: str, qids: list[str], topic_ids: list[str] | None = None,
               scoring: exams.Scoring | None = None, time_limit_s: int | None = None, shuffle: bool = False,
               extra: dict | None = None) -> None:
    if not qids:
        st.warning("No hay preguntas disponibles con esos criterios.")
        return
    eid = exams.create_exam(kind, mode, title, qids, topic_ids, scoring, time_limit_s, shuffle, extra)
    st.session_state["exam_id"] = eid
    st.session_state.pop("result_exam_id", None)
    st.session_state.pop("_tick", None)
    go("examen")


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    st.markdown(f'<div class="page-title">{icon} {title}</div>' + (f'<div class="page-sub">{subtitle}</div>' if subtitle else ""),
                unsafe_allow_html=True)


def mode_picker(key: str, default: str = "practica") -> str:
    opts = {"practica": "🎯 Práctica — corrección inmediata", "examen": "📝 Examen — corrección al final"}
    v = st.segmented_control("Modalidad", list(opts), format_func=lambda k: opts[k], default=default, key=key)
    return v or default


def timer_picker(key: str, n_questions: int | None = None) -> int | None:
    c1, c2 = st.columns([1, 1])
    timed = c1.toggle("Cronometrado", key=f"{key}_on")
    if not timed:
        return None
    default = max(5, int(round((n_questions or 30) * 1.0)))
    mins = c2.number_input("Minutos", min_value=1, max_value=600, value=default, step=5, key=f"{key}_min")
    return int(mins * 60)
