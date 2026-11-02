"""Componentes visuales reutilizables."""
from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

from core import bank, config, explain, srs, userdata
from core.bank import Question
from core.extract.test_parser import LETTERS


def esc(t: str | None) -> str:
    return html.escape(t or "")


def fmt_time(seconds: int | float | None) -> str:
    s = int(seconds or 0)
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min"
    return f"{s % 60} s"


def kpi(label: str, value: str, sub: str = "") -> None:
    st.markdown(f'<div class="kpi"><div class="lbl">{esc(label)}</div><div class="val">{esc(value)}</div>'
                f'<div class="sub">{esc(sub)}</div></div>', unsafe_allow_html=True)


def kpi_row(items: list[tuple[str, str, str]]) -> None:
    cols = st.columns(len(items))
    for c, (l, v, s) in zip(cols, items):
        with c:
            kpi(l, v, s)


def badge(kind: str, text: str) -> str:
    return f'<span class="badge b-{kind}">{esc(text)}</span>'


def topic_chip(tid: str | None) -> str:
    return f'<span class="topic-chip">{esc(bank.topic_label(tid, short=True))}</span>'


def empty_state(msg: str, icon: str = "🗂️") -> None:
    st.markdown(f'<div class="card" style="text-align:center;padding:28px"><div style="font-size:2rem">{icon}</div>'
                f'<div style="color:#52514e;margin-top:6px">{esc(msg)}</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ explicación

def _opt(options: list[str], letter: str | None) -> str:
    if not letter:
        return "—"
    i = LETTERS.index(letter)
    return f"{letter.upper()}) {options[i]}" if i < len(options) else letter.upper()


def explanation_panel(q: Question, selected: str | None, key: str, options: list[str] | None = None,
                      correct_letter: str | None = None, justification: str | None = None,
                      show_header: bool = True) -> None:
    """Panel de corrección. `options/correct_letter/justification` permiten usar la copia histórica de un examen."""
    options = options or q.options
    correct_letter = correct_letter or q.correct_letter
    just = justification if justification is not None else q.justification
    exp = explain.build(q, selected)
    ok = selected is not None and selected == correct_letter
    sol_src = f"{bank.doc_label(q.solution_doc_id)}" + (f" · pág. {q.solution_page}" if q.solution_page else "")

    if show_header:
        if ok:
            st.markdown('<div class="res-ok">✅ ¡Correcto!</div>', unsafe_allow_html=True)
        elif selected is None:
            st.markdown('<div class="res-ko" style="background:#f3f2ee;color:#52514e">⏺ Sin responder</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="res-ko">❌ Respuesta incorrecta</div>', unsafe_allow_html=True)

    ai = None
    ai_err = None
    ai_key = f"ai_{key}"
    if st.session_state.get(ai_key) or db_cached_ai(q.id, selected):
        try:
            ai = explain.ai_explain(exp)
        except Exception as e:  # noqa: BLE001
            ai_err = str(e)

    def body():
        if not ok and selected is not None:
            st.markdown(f'<div class="exp yours"><h4>Tu respuesta</h4>{esc(_opt(options, selected))}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="exp correct"><h4>Respuesta correcta {badge("oficial", "Solución oficial")}</h4>'
                    f'<b>{esc(_opt(options, correct_letter))}</b><div class="pg">Solucionario: {esc(sol_src)}</div></div>',
                    unsafe_allow_html=True)
        if not ok and selected is not None:
            if ai:
                st.markdown(f'<div class="exp why"><h4>¿Por qué es incorrecta tu respuesta? {badge("ia", "Generado por IA")}</h4>'
                            f'{esc(ai.get("por_que_incorrecta"))}</div>', unsafe_allow_html=True)
            else:
                txt = ("El solucionario oficial no analiza específicamente la opción que elegiste. "
                       f"La opción correcta es la {correct_letter.upper()}; revisa la justificación oficial y el fragmento "
                       "del temario de abajo para ver en qué se diferencia de tu respuesta.")
                if exp.has_specific_wrong_reason:
                    txt = "La justificación oficial menciona tu opción; léela abajo."
                st.markdown(f'<div class="exp why"><h4>¿Por qué es incorrecta tu respuesta?</h4>{esc(txt)}</div>', unsafe_allow_html=True)
        parts = []
        if just:
            parts.append(f'{badge("oficial", "Justificación oficial")}<div class="quote">«{esc(just)}»</div>')
        if ai and ai.get("por_que_correcta"):
            parts.append(f'<div style="margin-top:8px">{badge("ia", "Explicación generada por IA")}{esc(ai["por_que_correcta"])}</div>')
        if not parts:
            parts.append("Los documentos no incluyen justificación para esta respuesta.")
        st.markdown(f'<div class="exp correct"><h4>¿Por qué es correcta la respuesta {correct_letter.upper()}?</h4>{"".join(parts)}</div>',
                    unsafe_allow_html=True)
        if exp.theory:
            t = exp.theory[0]
            st.markdown(f'<div class="exp theory"><h4>Lo que dice el temario {badge("temario", "Cita literal")}</h4>'
                        f'<div class="quote">«{esc(t["text"])}»</div>'
                        f'<div class="pg">{esc(bank.doc_label(t["doc_id"]))} · {esc(t["section_title"])} · pág. {t["page"]}</div></div>',
                        unsafe_allow_html=True)
            if len(exp.theory) > 1:
                with st.expander("Más fragmentos relacionados del temario"):
                    for t in exp.theory[1:]:
                        st.markdown(f'<div class="quote">«{esc(t["text"])}»</div><div class="pg">{esc(bank.doc_label(t["doc_id"]))} · '
                                    f'{esc(t["section_title"])} · pág. {t["page"]}</div><br>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="exp theory"><h4>Temario</h4>No se ha encontrado un fragmento del temario relacionado: '
                        'la explicación se limita al solucionario.</div>', unsafe_allow_html=True)
        rem = (ai or {}).get("recuerda") or exp.remember
        if rem:
            b = badge("ia", "IA") if (ai and ai.get("recuerda")) else badge("extracto", "Extraído del solucionario")
            st.markdown(f'<div class="exp remember"><h4>💡 Recuerda {b}</h4><b>{esc(rem)}</b></div>', unsafe_allow_html=True)
        if ai and not ai.get("suficiente", True):
            st.info(f"La IA indica que los documentos no bastan para justificarlo del todo: {ai.get('limitaciones', '')}")
        src = [f"<b>Tema:</b> {esc(bank.topic_label(q.topic_id))}"]
        if exp.theory:
            t = exp.theory[0]
            src.append(f"<b>Apartado:</b> {esc(t['section_title'])} ({esc(bank.doc_label(t['doc_id']))}, pág. {t['page']})")
        src.append(f"<b>Pregunta original:</b> {esc(bank.doc_label(q.source_doc_id))}, nº {q.source_number}, pág. {q.source_page}")
        src.append(f"<b>Solución:</b> {esc(sol_src)}")
        st.markdown(f'<div class="exp source"><h4>Fuente</h4>{"<br>".join(src)}</div>', unsafe_allow_html=True)

        if not ai:
            if explain.ai_available():
                if st.button("✨ Explicación ampliada con IA (basada solo en el temario)", key=f"btn_{ai_key}"):
                    st.session_state[ai_key] = True
                    st.rerun()
            if ai_err:
                st.warning(ai_err)

    if ok:
        with st.expander("Ver explicación"):
            body()
    else:
        body()


def db_cached_ai(qid: str, selected: str | None) -> bool:
    from core import db
    key = explain._cache_key("explain-v1", explain.AI_MODEL, qid, selected or "-")
    return db.scalar("SELECT 1 FROM ai_cache WHERE key=?", (key,)) is not None


# ------------------------------------------------------------------ tarjeta de pregunta (listas)

def fav_note_controls(qid: str, key: str) -> None:
    c1, c2 = st.columns([1, 3])
    fav = userdata.is_favorite(qid)
    if c1.button("★ Quitar de favoritas" if fav else "☆ Añadir a favoritas", key=f"fav_{key}"):
        userdata.toggle_favorite(qid)
        st.rerun()
    note = userdata.get_note(qid)
    with c2.popover("📝 Nota personal" + (" ✓" if note else ""), width="stretch"):
        txt = st.text_area("Tu nota", value=note, key=f"note_{key}", height=120)
        if st.button("Guardar nota", key=f"savenote_{key}"):
            userdata.save_note(qid, txt)
            st.toast("Nota guardada")


def question_view(q: Question, selected: str | None = None, key: str = "", show_explanation: bool = True,
                  snapshot: dict | None = None) -> None:
    """Muestra una pregunta completa con opciones marcadas y su explicación."""
    options = snapshot["options"] if snapshot else q.options
    correct = snapshot["correct_letter"] if snapshot else q.correct_letter
    st.markdown(f'{topic_chip(q.topic_id)}<div class="q-stem">{esc(snapshot["stem"] if snapshot else q.stem)}</div>',
                unsafe_allow_html=True)
    rows = []
    for i, o in enumerate(options):
        L = LETTERS[i]
        style = ""
        mark = ""
        if correct and L == correct:
            style, mark = "background:#e3f5e3;border-color:#0ca30c", " ✅"
        elif selected == L:
            style, mark = "background:#fde8e8;border-color:#d03b3b", " ❌ (tu respuesta)"
        rows.append(f'<div class="exp" style="{style}"><b>{L.upper()})</b> {esc(o)}{mark}</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    note = userdata.get_note(q.id)
    if note:
        st.markdown(f'<div class="exp remember"><h4>📝 Tu nota</h4>{esc(note)}</div>', unsafe_allow_html=True)
    if show_explanation and correct:
        explanation_panel(q, selected, key, options=options, correct_letter=correct,
                          justification=snapshot.get("justification") if snapshot else None, show_header=False)
    elif not correct:
        st.markdown(f'<div class="exp source">{badge("pend", "Pendiente de revisión")} {esc(q.status_reason)}</div>',
                    unsafe_allow_html=True)
    fav_note_controls(q.id, key)


def image_path(rel: str) -> Path:
    return config.DOCS_DIR / rel


def review_list(answers: list[dict], key: str, practice_mode: bool = False) -> None:
    """Revisión completa de un examen (con la copia histórica de cada pregunta)."""
    filt = st.segmented_control("Mostrar", ["Todas", "Falladas", "En blanco", "Acertadas", "Marcadas"], default="Todas",
                                key=f"rf_{key}")
    qs = bank.get_questions([a["question_id"] for a in answers])
    shown = 0
    for a in answers:
        ok = a["selected"] is not None and a["is_correct"]
        ko = a["selected"] is not None and not a["is_correct"]
        blank = a["selected"] is None
        if filt == "Falladas" and not ko or filt == "En blanco" and not blank or filt == "Acertadas" and not ok \
                or filt == "Marcadas" and not a["flagged"]:
            continue
        shown += 1
        icon = "✅" if ok else ("❌" if ko else "⏺")
        q = qs.get(a["question_id"])
        with st.expander(f"{icon} {a['position'] + 1}. {a['stem'][:110]}{'…' if len(a['stem']) > 110 else ''}"
                         + ("  ⚑" if a["flagged"] else "")):
            if q is None:
                st.caption("Esta pregunta ya no está en el banco actual; se muestra la copia guardada.")
                for i, o in enumerate(a["options"]):
                    st.write(f"{LETTERS[i].upper()}) {o}")
                st.write(f"Respuesta oficial: {a['correct_letter'].upper()}")
            else:
                question_view(q, a["selected"], key=f"{key}_{a['position']}", snapshot=a)
    if not shown:
        st.caption("No hay preguntas en esta categoría.")
