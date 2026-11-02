"""Generador de resúmenes (extractivos, con página) y resumen de mis errores."""
from __future__ import annotations

import streamlit as st

from core import bank, explain, summaries
from ui import nav
from ui.components import badge, empty_state, esc

TIPOS = {"completo": "Resumen completo", "apartados": "Por apartados", "rapido": "Resumen rápido",
         "esquema": "Esquema de estudio", "errores": "Resumen de mis errores"}

NOTE = (f'{badge("extracto", "Extractos literales")} Las frases son citas exactas del temario seleccionadas '
        "automáticamente (por su relación con lo que preguntan los test, artículos, plazos y definiciones). "
        "No se ha añadido contenido.")


def _quote(text: str, page: int, extra: str = "") -> None:
    st.markdown(f'<div class="quote" style="margin:4px 0 2px 0">«{esc(text)}»</div>'
                f'<div class="pg">pág. {page}{(" · " + esc(extra)) if extra else ""}</div>', unsafe_allow_html=True)


def _ai_button(title: str, passages: list[dict], kind: str, key: str) -> None:
    if not explain.ai_available() or not passages:
        return
    k = f"ais_{key}_{kind}"
    if st.button("✨ Redactar este resumen con IA (solo con estos textos)", key=f"b{k}") or st.session_state.get(k):
        st.session_state[k] = True
        try:
            with st.spinner("Generando…"):
                txt = explain.ai_summary(title, passages, kind)
            st.markdown(f'{badge("ia", "Generado por IA — no es cita literal; verifica con el temario")}', unsafe_allow_html=True)
            st.markdown(txt or "")
        except RuntimeError as e:
            st.warning(str(e))


def summary_panel(tid: str | None, key: str, default: str | None = None) -> None:
    tipo = st.segmented_control("Tipo de resumen", list(TIPOS), format_func=TIPOS.get, default=default or "rapido",
                                key=f"rt_{key}") or "rapido"
    if tipo == "errores":
        _errors(tid, key)
        return
    if not tid:
        st.info("Selecciona un tema.")
        return
    title = bank.topic_label(tid)
    if tipo == "completo":
        st.markdown(NOTE, unsafe_allow_html=True)
        data = summaries.summary_by_section(tid, per_section=3)
        passages = []
        for d in data:
            s = d["section"]
            if not d["sentences"] and s["level"] > 2:
                continue
            st.markdown(f"{'#' * min(s['level'] + 2, 6)} {s['title']}")
            for x in d["sentences"]:
                _quote(x.text, x.page)
                passages.append({"page": x.page, "text": x.text})
        _ai_button(title, passages, "completo", key)
    elif tipo == "apartados":
        secs = bank.sections_for_topic(tid)
        chosen = st.multiselect("Apartados", [s["id"] for s in secs],
                                format_func=lambda i: next(s["title"][:90] for s in secs if s["id"] == i), key=f"ra_{key}")
        full = st.toggle("Mostrar texto íntegro del apartado", key=f"rf_{key}")
        if not chosen:
            return
        st.markdown(NOTE, unsafe_allow_html=True)
        passages = []
        for d in summaries.summary_by_section(tid, per_section=6, section_ids=chosen):
            s = d["section"]
            st.markdown(f"#### {s['title']}")
            if full:
                for p in (s["text"] or "").split("\n\n"):
                    st.markdown(f'<p class="theory-p">{esc(p)}</p>', unsafe_allow_html=True)
                passages.append({"page": s["page"], "text": s["text"]})
            else:
                for x in d["sentences"]:
                    _quote(x.text, x.page)
                    passages.append({"page": x.page, "text": x.text})
        _ai_button(title, passages, "completo", key + "ap")
    elif tipo == "rapido":
        st.markdown(NOTE, unsafe_allow_html=True)
        sents = summaries.quick_summary(tid, 20)
        for i, x in enumerate(sents, 1):
            _quote(f"{x.text}", x.page, x.section_title[:60])
        _ai_button(title, [{"page": x.page, "text": x.text} for x in sents], "rapido", key)
    elif tipo == "esquema":
        st.markdown(f'{badge("temario", "Estructura original")} Índice jerárquico del temario con el nº de preguntas de test vinculadas '
                    "a cada apartado (más preguntas = más importante).", unsafe_allow_html=True)
        lines = []
        for o in summaries.outline(tid):
            ind = "    " * max(o["level"] - 1, 0)
            qn = f" — **{o['n_questions']} preg.**" if o["n_questions"] else ""
            lines.append(f"{ind}- {o['title'][:110]} _(pág. {o['page']})_{qn}")
        st.markdown("\n".join(lines))
        es = bank.esquemas_for_topic(tid)
        if es:
            st.caption(f"Este tema tiene además {len(es)} esquemas visuales: pestaña «Esquemas» de Estudiar temario.")


def _errors(tid: str | None, key: str) -> None:
    scope = st.radio("Ámbito", ["Este tema", "Todos los temas"] if tid else ["Todos los temas"], horizontal=True, key=f"re_{key}")
    pats = summaries.error_patterns([tid] if (tid and scope == "Este tema") else None, min_fails=2)
    if not pats:
        empty_state("No hay errores registrados todavía.", "🎉")
        return
    strong = [p for p in pats if p["pattern"]]
    if strong:
        st.error(f"🚨 Patrones detectados: fallas varias preguntas de **{len(strong)}** apartado(s). Te proponemos estudiarlos primero.")
    else:
        st.info("No hay apartados con 2 o más preguntas falladas; se muestran tus errores por apartado.")
    st.markdown(NOTE, unsafe_allow_html=True)
    passages = []
    for p in pats[:15]:
        icon = "🚨" if p["pattern"] else "•"
        with st.expander(f"{icon} {bank.topic_label(p['topic_id'], short=True)} · {p['title'][:80]} — {len(p['questions'])} preguntas, "
                         f"{p['fails']} fallos", expanded=p["pattern"]):
            st.caption(f"{bank.doc_label(p['doc_id'])} · pág. {p['page']} · {p['still_failing']} siguen falladas")
            data = summaries.summary_by_section(p["topic_id"], per_section=4, section_ids=[p["section_id"]])
            for d in data:
                for x in d["sentences"]:
                    _quote(x.text, x.page)
                    passages.append({"page": x.page, "text": x.text})
            qs = bank.get_questions(p["questions"])
            st.markdown("**Preguntas que fallaste de este apartado:**")
            for i in p["questions"]:
                q = qs[i]
                st.markdown(f"- {esc(q.stem)}  \n  ✅ **{q.correct_letter.upper()}) {esc(q.correct_text)}**")
            c1, c2 = st.columns(2)
            if c1.button("Practicar estas preguntas", key=f"rep_{key}_{p['section_id']}"):
                nav.start_exam("fallos", "practica", f"Errores · {p['title'][:50]}", p["questions"], [p["topic_id"]])
            if c2.button("Ir al apartado en el temario", key=f"go_{key}_{p['section_id']}"):
                st.session_state[f"th_sec_{p['topic_id']}_{p['doc_id']}"] = p["section_id"]
                nav.go("temario", temario_topic=p["topic_id"])
    _ai_button("Mis errores", passages, "errores", key)


def render() -> None:
    nav.page_header("Generador de resúmenes", "Resúmenes extractivos del temario, esquemas y análisis de tus errores.", "🧾")
    from ui.views.test_tema import topic_selector
    tid = topic_selector("res_sel", include_empty=True)
    summary_panel(tid if tid != "CP" else None, key="pg", default=st.session_state.pop("resumen_tipo", None))
