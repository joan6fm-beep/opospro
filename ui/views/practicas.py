"""Prácticas de clase: test con corrección y supuesto práctico de desarrollo con autocorrección."""
from __future__ import annotations

import json
import re

import pandas as pd
import streamlit as st

from core import bank, config, db, exams, srs
from core.extract.test_parser import LETTERS
from ui import nav
from ui.components import esc, kpi_row

KIND = "practica"
SELF_KEY = "practicas_desarrollo"  # historial de autocorrecciones del supuesto (tabla settings: se sincroniza)
GRADES = {"bien": "✅ Bien", "regular": "🟡 Regular", "mal": "❌ Mal"}


@st.cache_data(show_spinner=False)
def _catalog() -> list[dict]:
    # sin importar core.ingest (cargaría PyMuPDF al abrir la página)
    path = config.ROOT / "core" / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8")).get("practicas", [])


def _exists(rel: str | None) -> bool:
    return bool(rel) and (config.DOCS_DIR / rel).exists()


# ------------------------------------------------------------------ práctica tipo test

def _attempts(test_id: str) -> list[dict]:
    return [h for h in exams.history(kind=KIND) if h["config"].get("test_id") == test_id]


def _test_practice(p: dict, title: str) -> None:
    t = bank.test_by_doc(p["test"]) if p.get("test") else None
    if t is None:
        st.info("Práctica preparada: todavía no está su documento en la carpeta *Benicasim/PRACTICAS*. "
                "Cuando lo añadas, pulsa *Banco y ajustes → Importar → Reimportar*.", icon="📭")
        return
    qids = bank.test_question_ids(t["id"])
    all_ids = bank.test_question_ids(t["id"], scoreable_only=False)
    pending = [i for i in all_ids if i not in set(qids)]
    states = srs.all_states()
    failed = [i for i in qids if i in states and states[i]["n_wrong"] > 0 and states[i]["last_result"] == 0]
    hist = _attempts(t["id"])
    best = max((h["grade"] for h in hist), default=None)
    kpi_row([("Preguntas", str(len(qids)), f"de {len(all_ids)} en el documento"),
             ("Intentos", str(len(hist)), ""),
             ("Última nota", f"{hist[0]['grade']:.2f}" if hist else "—",
              f"{hist[0]['n_correct']} aciertos · {hist[0]['n_wrong']} fallos" if hist else ""),
             ("Mejor nota", f"{best:.2f}" if best is not None else "—", "sobre 10")])
    if not qids:
        st.warning(f"El documento no trae solucionario: sus {len(all_ids)} preguntas no se pueden corregir sin inventar "
                   "respuestas. Añade el solucionario oficial de esta clase a *Benicasim/PRACTICAS* y reimporta: "
                   "la práctica se activará sola.", icon="📝")
    else:
        key = f"pr{p['n']}"
        mode = nav.mode_picker(f"{key}_mode")
        tl = nav.timer_picker(f"{key}_timer", len(qids))
        c1, c2, c3 = st.columns(3)
        extra = {"test_id": t["id"], "practica": p["n"]}
        if c1.button(f"▶️ Hacer práctica ({len(qids)})", key=f"{key}_go", type="primary", width="stretch"):
            nav.start_exam(KIND, mode, title, qids, ["CP"], time_limit_s=tl, extra=extra)
        if c2.button("🔀 Orden aleatorio", key=f"{key}_rnd", width="stretch"):
            nav.start_exam(KIND, mode, f"{title} · aleatoria", qids, ["CP"], time_limit_s=tl, shuffle=True, extra=extra)
        if c3.button(f"❌ Repetir falladas ({len(failed)})", key=f"{key}_ko", width="stretch", disabled=not failed):
            nav.start_exam("fallos", mode, f"{title} · falladas", failed, ["CP"], time_limit_s=tl)
    if pending and qids:
        st.caption(f"⚠️ {len(pending)} pregunta(s) sin respuesta en el solucionario: se muestran abajo, pero no puntúan.")
    if pending:
        with st.expander(f"📄 Ver preguntas sin solucionario ({len(pending)})"):
            qs = bank.get_questions(pending)
            for i in pending:
                q = qs[i]
                st.markdown(f"**{q.source_number}. {esc(q.stem)}**  \n" +
                            "  \n".join(f"{LETTERS[k]}) {esc(o)}" for k, o in enumerate(q.options)))
    if hist:
        st.markdown("**Resultados anteriores**")
        st.dataframe(pd.DataFrame([{
            "Fecha": h["finished_at"][:16].replace("T", " "), "Nota": h["grade"], "Aciertos": h["n_correct"],
            "Fallos": h["n_wrong"], "En blanco": h["n_blank"], "% acierto": h["pct"],
            "Modo": "Práctica" if h["mode"] == "practica" else "Examen"} for h in hist]),
            hide_index=True, width="stretch",
            column_config={"Nota": st.column_config.ProgressColumn("Nota", min_value=0, max_value=10, format="%.2f"),
                           "% acierto": st.column_config.NumberColumn(format="%.0f %%")})
        st.caption("La revisión pregunta a pregunta está en *Historial*.")


# ------------------------------------------------------------------ supuesto de desarrollo

def _md(t: str) -> str:
    return re.sub(r"([$*_#`\\])", r"\\\1", t)


def _items(lines) -> list[list]:
    """Agrupa las líneas del PDF en títulos, viñetas y párrafos: [tipo, texto, bloque]."""
    out: list[list] = []
    bullet = False
    for ln in lines:
        t = ln.text.strip()
        if t in ("•", "-"):
            bullet = True
            continue
        if t.startswith("• "):
            out.append(["li", t[2:], ln.block])
            bullet = False
            continue
        if ln.bold:
            # un título partido en dos líneas continúa en minúscula; si empieza en mayúscula es otro título
            if out and out[-1][0] == "h" and out[-1][2] == ln.block and t[:1].islower():
                out[-1][1] += " " + t
            else:
                out.append(["h", t, ln.block])
            continue
        if re.match(r"^\d{1,2}\.\s+\S", t):  # lista numerada («1. Sábado 10 de octubre: …»)
            out.append(["ol", t, ln.block])
            bullet = False
            continue
        if bullet:
            out.append(["li", t, ln.block])
            bullet = False
        elif out and out[-1][0] in ("li", "ol", "p") and out[-1][2] == ln.block:
            out[-1][1] += " " + t
        else:
            out.append(["p", t, ln.block])
    return out


def _render(items: list[list]) -> str:
    def one(k, x):
        if k == "h":
            return f"**{_md(x)}**"
        if k == "li":
            return f"- {_md(x)}"
        if k == "ol":
            n, rest = x.split(".", 1)
            return f"{n}\\. {_md(rest.strip())}"  # número literal: cada punto es un párrafo propio
        return _md(x)
    return "\n\n".join(one(k, x) for k, x, _ in items)


@st.cache_data(show_spinner=False)
def _supuesto(rel_case: str, rel_sol: str | None) -> dict:
    from core.extract.pdf_reader import read_lines
    items = _items(read_lines(config.DOCS_DIR / rel_case))
    hechos, preguntas, cur, zone = [], {}, None, "intro"
    for it in items:
        m = re.match(r"^Pregunta\s+(\d+)\b", it[1]) if it[0] == "h" else None
        if it[0] == "h" and it[1].upper().startswith("PREGUNTAS A DESARROLLAR"):
            zone = "preguntas"
            continue
        if m:
            cur = int(m.group(1))
            preguntas[cur] = []
            continue
        if it[0] == "h" and it[1].upper() in ("SUPUESTO PRÁCTICO", "HECHOS"):
            zone = "hechos"
            continue
        (preguntas[cur] if cur and zone == "preguntas" else hechos).append(it)
    sols: dict[int, tuple[str, list]] = {}
    if rel_sol and (config.DOCS_DIR / rel_sol).exists():
        cur = None
        for it in _items(read_lines(config.DOCS_DIR / rel_sol)):
            m = re.match(r"^Pregunta\s+(\d+)\s*:?\s*(.*)$", it[1]) if it[0] == "h" else None
            if m:
                cur = int(m.group(1))
                sols[cur] = (m.group(2), [])
            elif cur:
                sols[cur][1].append(it)
    return {"hechos": _render(hechos),
            "preguntas": {n: _render(v) for n, v in sorted(preguntas.items())},
            "soluciones": {n: (t, _render(v)) for n, (t, v) in sols.items()}}


def _case_practice(p: dict, title: str) -> None:
    if not _exists(p.get("supuesto")):
        st.info("Práctica preparada: todavía no está su documento en la carpeta *Benicasim/PRACTICAS*.", icon="📭")
        return
    data = _supuesto(p["supuesto"], p.get("soluciones"))
    n_q = len(data["preguntas"])
    hist = [h for h in (db.get_setting(SELF_KEY, []) or []) if h.get("practica") == p["n"]]
    best = max((h["nota"] for h in hist), default=None)
    kpi_row([("Preguntas", str(n_q), "de desarrollo"), ("Intentos", str(len(hist)), ""),
             ("Última nota", f"{hist[-1]['nota']:.2f}" if hist else "—",
              f"{hist[-1]['bien']} bien · {hist[-1]['mal']} mal" if hist else ""),
             ("Mejor nota", f"{best:.2f}" if best is not None else "—", "sobre 10")])
    st.caption("Supuesto de desarrollo: no tiene opciones A-D, así que la corrección es tuya. Escribe tu respuesta, "
               "ábrela junto a la solución oficial y marca cada pregunta como Bien (1), Regular (0,5) o Mal (0).")
    with st.expander("📋 Hechos del supuesto", expanded=True):
        st.markdown(data["hechos"])
    run = st.session_state.setdefault(f"case{p['n']}_run", 0)
    grades = {}
    for n, enun in data["preguntas"].items():
        with st.container(border=True):
            st.markdown(f"**Pregunta {n}**\n\n{enun}")
            st.text_area("Tu respuesta (opcional, no se guarda)", key=f"case{p['n']}_{run}_a{n}", height=110)
            sol = data["soluciones"].get(n)
            with st.expander("🔑 Ver solución oficial" + (f" · {sol[0]}" if sol and sol[0] else "")):
                st.markdown(sol[1] if sol else "_El solucionario no incluye esta pregunta._")
            grades[n] = st.segmented_control("Autocorrección", list(GRADES), format_func=GRADES.get,
                                             key=f"case{p['n']}_{run}_g{n}")
    done = {n: g for n, g in grades.items() if g}
    c1, c2 = st.columns(2)
    if c1.button(f"💾 Guardar corrección ({len(done)}/{n_q})", key=f"case{p['n']}_save", type="primary",
                 width="stretch", disabled=not done):
        bien = sum(1 for g in done.values() if g == "bien")
        reg = sum(1 for g in done.values() if g == "regular")
        mal = sum(1 for g in done.values() if g == "mal")
        nota = round((bien + 0.5 * reg) / n_q * 10, 2)
        allh = db.get_setting(SELF_KEY, []) or []
        allh.append({"practica": p["n"], "fecha": srs.iso(srs.now()), "nota": nota, "bien": bien, "regular": reg,
                     "mal": mal, "sin_corregir": n_q - len(done), "detalle": {str(k): v for k, v in done.items()}})
        db.set_setting(SELF_KEY, allh)
        st.session_state[f"case{p['n']}_run"] = run + 1
        st.toast(f"Guardado: nota {nota:.2f} / 10")
        st.rerun()
    if c2.button("🔄 Empezar de nuevo", key=f"case{p['n']}_reset", width="stretch"):
        st.session_state[f"case{p['n']}_run"] = run + 1
        st.rerun()
    if hist:
        st.markdown("**Resultados anteriores**")
        st.dataframe(pd.DataFrame([{"Fecha": h["fecha"][:16].replace("T", " "), "Nota": h["nota"], "Bien": h["bien"],
                                    "Regular": h["regular"], "Mal": h["mal"], "Sin corregir": h["sin_corregir"]}
                                   for h in reversed(hist)]),
                     hide_index=True, width="stretch",
                     column_config={"Nota": st.column_config.ProgressColumn("Nota", min_value=0, max_value=10, format="%.2f")})


# ------------------------------------------------------------------ página

def render() -> None:
    nav.page_header("Prácticas", "Ejercicios de las clases prácticas con su solucionario oficial.", "🧩")
    prs = _catalog()
    if not prs:
        st.info("No hay prácticas configuradas.")
        return
    tabs = st.tabs([f"Práctica {p['n']}" for p in prs])
    for tab, p in zip(tabs, prs):
        with tab:
            title = f"Práctica {p['n']}" + (f" · clase {p['fecha']}" if p.get("fecha") else "")
            st.markdown(f"#### {esc(title)}")
            if p.get("supuesto"):
                _case_practice(p, title)
            else:
                _test_practice(p, title)
