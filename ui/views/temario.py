"""Estudio del temario: teoría original, esquemas, resúmenes, conceptos, preguntas y errores por tema."""
from __future__ import annotations

import time

import streamlit as st

from core import bank, config, exams, summaries
from core.extract.pdf_reader import render_page_png
from ui import nav
from ui.components import badge, empty_state, esc, question_view
from ui.views import resumenes
from ui.views.test_tema import topic_selector


@st.cache_data(show_spinner=False, max_entries=64)
def page_png(doc_id: str, page: int) -> bytes:
    return render_page_png(config.DOCS_DIR / doc_id, page)


def _log_time(tid: str) -> None:
    now = time.time()
    last = st.session_state.get("_study_tick")
    if last and st.session_state.get("_study_topic") == tid:
        summaries.log_study_time(tid, int(min(now - last, 300)))
    st.session_state["_study_tick"] = now
    st.session_state["_study_topic"] = tid


def _theory(tid: str) -> None:
    secs = bank.sections_for_topic(tid)
    if not secs:
        empty_state("Este tema no tiene documento de teoría.")
        return
    docs = list(dict.fromkeys(s["doc_id"] for s in secs))
    doc = st.radio("Documento", docs, format_func=bank.doc_label, horizontal=True, key=f"th_doc_{tid}") if len(docs) > 1 else docs[0]
    dsecs = [s for s in secs if s["doc_id"] == doc]
    labels = {s["id"]: ("　" * max(s["level"] - 1, 0)) + s["title"][:90] for s in dsecs}
    c1, c2 = st.columns([1, 2.4])
    with c1:
        st.caption("Apartados")
        sid = st.radio("Apartado", [s["id"] for s in dsecs], format_func=lambda i: labels[i], key=f"th_sec_{tid}_{doc}",
                       label_visibility="collapsed", index=0)
    with c2:
        s = next(x for x in dsecs if x["id"] == sid)
        st.markdown(f"### {esc(s['title'])}")
        st.markdown(f'{badge("temario", "Texto original")} <span class="pg">{esc(bank.doc_label(doc))} · desde pág. {s["page"]}</span>',
                    unsafe_allow_html=True)
        idx = dsecs.index(s)
        shown = [s] + [x for x in dsecs[idx + 1:idx + 8] if x["level"] > s["level"]][:6] if s["level"] <= 1 else [s]
        if not s["text"] and len(shown) == 1:
            st.caption("Este apartado solo contiene subapartados; selecciona uno a la izquierda.")
        for x in shown:
            if x is not s:
                st.markdown(f'<div class="sec-title">{esc(x["title"])}</div>', unsafe_allow_html=True)
            for p in [p for p in (x["text"] or "").split("\n\n") if p.strip()]:
                st.markdown(f'<p class="theory-p">{esc(p)}</p>', unsafe_allow_html=True)
        q_ids = bank.questions_for_section(sid)
        if q_ids:
            if st.button(f"❓ Practicar las {len(q_ids)} preguntas vinculadas a este apartado", key=f"thq_{sid}"):
                qs = bank.get_questions(q_ids)
                nav.start_exam("tema_aleatorio", "practica", f"Apartado: {s['title'][:60]}",
                               [i for i in q_ids if qs[i].scoreable], [tid], shuffle=True)
        with st.expander("📄 Ver la página original del PDF (con tablas e imágenes)"):
            n_pages = bank.documents(topic_id=tid)
            pages = next((d["pages"] for d in n_pages if d["id"] == doc), s["page"])
            pg = st.number_input("Página", 1, pages, s["page"], key=f"pg_{tid}_{doc}_{sid}")
            st.image(page_png(doc, int(pg)), width="stretch")


def _esquemas(tid: str) -> None:
    es = bank.esquemas_for_topic(tid)
    if not es:
        empty_state("No hay esquemas visuales para este tema.")
        return
    st.caption(f"{len(es)} esquemas de la carpeta Resumen (imágenes originales).")
    labels = sorted({e["label"] for e in es})
    for lab in labels:
        if lab:
            st.markdown(f"**{esc(lab)}**")
        group = [e for e in es if e["label"] == lab]
        i = st.select_slider("Esquema", options=list(range(len(group))), format_func=lambda k: f"{k + 1} / {len(group)}",
                             key=f"esq_{tid}_{lab}") if len(group) > 1 else 0
        st.image(str(config.DOCS_DIR / group[i]["path"]), width="stretch", caption=group[i]["path"])


def _key_concepts(tid: str) -> None:
    st.markdown(f'{badge("extracto", "Calculado de tus documentos")} Referencias normativas más preguntadas en los test del tema:',
                unsafe_allow_html=True)
    terms = summaries.key_terms(tid, 30)
    if terms:
        st.markdown(" ".join(f'<span class="topic-chip">{esc(t)} · {n}</span>' for t, n in terms), unsafe_allow_html=True)
    st.markdown("#### Apartados más preguntados")
    ol = sorted([o for o in summaries.outline(tid) if o["n_questions"]], key=lambda o: -o["n_questions"])[:10]
    for o in ol:
        st.markdown(f"- **{esc(o['title'][:100])}** — {o['n_questions']} preguntas (pág. {o['page']})")
    st.markdown("#### Frases clave")
    for s in summaries.quick_summary(tid, 10):
        st.markdown(f'<div class="quote">«{esc(s.text)}»</div><div class="pg">{esc(s.section_title[:70])} · pág. {s.page}</div>',
                    unsafe_allow_html=True)


def _related(tid: str) -> None:
    outl = [o for o in summaries.outline(tid) if o["n_questions"]]
    if not outl:
        empty_state("No hay preguntas vinculadas a este temario.")
        return
    sid = st.selectbox("Apartado", [o["id"] for o in outl],
                       format_func=lambda i: next(f"{o['title'][:90]} ({o['n_questions']})" for o in outl if o["id"] == i))
    ids = bank.questions_for_section(sid)
    qs = bank.get_questions(ids)
    for i in ids:
        with st.expander(qs[i].stem[:120]):
            question_view(qs[i], None, key=f"rel_{i}")


def _my_errors(tid: str) -> None:
    pats = summaries.error_patterns([tid], min_fails=1)
    if not pats:
        empty_state("No tienes errores registrados en este tema.", "🎉")
        return
    for p in pats:
        star = "🚨 Patrón de error · " if len(p["questions"]) >= 2 else ""
        with st.expander(f"{star}{p['title'][:90]} — {len(p['questions'])} preguntas falladas", expanded=len(p["questions"]) >= 2):
            st.caption(f"{bank.doc_label(p['doc_id'])} · pág. {p['page']}")
            sec = summaries.section_text(p["section_id"])
            for para in (sec["text"] or "").split("\n\n")[:4]:
                st.markdown(f'<p class="theory-p">{esc(para)}</p>', unsafe_allow_html=True)
            qs = bank.get_questions(p["questions"])
            for i in p["questions"]:
                st.markdown(f"- ❌ {esc(qs[i].stem)} → **{qs[i].correct_letter.upper()}) {esc(qs[i].correct_text)}**")
            if st.button("Practicar estas preguntas", key=f"pe_{p['section_id']}"):
                nav.start_exam("fallos", "practica", f"Errores · {p['title'][:50]}", p["questions"], [tid])


def _documents(tid: str) -> None:
    docs = bank.documents(topic_id=tid)
    for d in docs:
        if d["kind"] == "esquema":
            continue
        st.markdown(f"- **{esc(d['id'])}** · {d['kind']} · {d['pages']} págs.")
    eq = bank.documents(kind="equivalencias")
    if eq:
        with st.expander("🔀 Equivalencias de temario Benicàssim – Almassora"):
            d = eq[0]
            for pg in range(1, d["pages"] + 1):
                st.image(page_png(d["id"], pg), width="stretch")


def render() -> None:
    nav.page_header("Estudiar temario", "Todo procede de tus documentos: teoría original, esquemas y resúmenes con su página de origen.", "📚")
    tid = topic_selector("temario_sel", st.session_state.pop("temario_topic", None), include_empty=True)
    if not tid or tid == "CP":
        if tid == "CP":
            _cases()
        return
    _log_time(tid)
    t = bank.topic(tid)
    st.caption(esc(t["title"]))
    tabs = st.tabs(["📖 Teoría", "🖼️ Esquemas", "🧾 Resúmenes", "🔑 Conceptos clave", "❓ Preguntas", "❌ Mis errores", "📄 Documentos"])
    with tabs[0]:
        _theory(tid)
    with tabs[1]:
        _esquemas(tid)
    with tabs[2]:
        resumenes.summary_panel(tid, key="tm")
    with tabs[3]:
        _key_concepts(tid)
    with tabs[4]:
        _related(tid)
    with tabs[5]:
        _my_errors(tid)
    with tabs[6]:
        _documents(tid)


def _cases() -> None:
    st.info("Casos prácticos: el test de «Práctica 1» no tiene solucionario en tus documentos, por eso sus preguntas "
            "están pendientes de revisión y no puntúan. Puedes leerlas aquí y en «Banco y ajustes» introducir la solución "
            "si la verificas con tu profesor.")
    for d in bank.documents(topic_id="CP"):
        with st.expander(f"📄 {d['id']} ({d['pages']} págs.)"):
            for pg in range(1, d["pages"] + 1):
                st.image(page_png(d["id"], pg), width="stretch")
