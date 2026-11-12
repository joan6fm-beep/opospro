"""Importación del material: inventario, extracción, verificación, duplicados y vínculos con la teoría.

Uso:  python -m core.ingest
Los documentos originales solo se leen; nunca se modifican.
Las tablas de progreso del usuario no se tocan: las preguntas usan un identificador estable
(hash del enunciado + opciones), por lo que reimportar no duplica preguntas ni pierde el historial.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, db
from .extract.docx_reader import docx_pages, docx_title, read_docx_lines
from .extract.pdf_reader import file_hash, page_count, read_lines, title_page_info
from .extract.test_parser import (LETTERS, ParsedQuestion, ParsedSolution, normalize,
                                  parse_questions, parse_solutions)
from .extract.theory_parser import parse_theory
from .search import BM25

DOC_EXT = {".pdf", ".docx"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
CATALOG = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- utilidades

def rel(p: Path) -> str:
    return p.relative_to(config.DOCS_DIR).as_posix()


def lines_of(p: Path):
    return read_docx_lines(p) if p.suffix.lower() == ".docx" else read_lines(p)


def pages_of(p: Path) -> int:
    return docx_pages(p) if p.suffix.lower() == ".docx" else page_count(p)


def cover_of(p: Path) -> tuple[str, str]:
    return docx_title(p) if p.suffix.lower() == ".docx" else title_page_info(p)


def question_uid(stem: str, options: list[str]) -> str:
    key = normalize(stem) + "||" + "|".join(normalize(o) for o in options)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def topic_id(anexo: str, num: int) -> str:
    return f"A{1 if anexo == 'I' else 2}-T{num:02d}"


def classify_name(name: str) -> str:
    n = normalize(name)
    if "solucion" in n:
        return "soluciones"
    if "equivalencia" in n:
        return "equivalencias"
    if n.startswith("test") or " test " in f" {n} ":
        return "test"
    return "otro"


def iter_files():
    for p in sorted(config.DOCS_DIR.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(config.DOCS_DIR).parts
        if parts[0] in config.EXCLUDED_DIRS or parts[0].startswith(".") or len(parts) < 2:
            continue
        yield p


# --------------------------------------------------------------------------- estructuras

@dataclass
class TopicInfo:
    id: str
    anexo: str
    number: int
    title: str = ""
    folder: str = ""
    titles: list[str] = field(default_factory=list)


@dataclass
class Report:
    documents: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)

    def issue(self, kind: str, doc: str | None, detail: str, qid: str | None = None):
        self.issues.append({"kind": kind, "doc": doc, "question_id": qid, "detail": detail})


TEMA_RE = re.compile(r"tema\s*(\d+)", re.I)
ANEXO2_RE = re.compile(r"anexo\s*(ii|2)\b", re.I)


def cover_title(full_cover: str) -> str:
    lines = [l.strip() for l in full_cover.splitlines() if l.strip()]
    out = []
    started = False
    for l in lines:
        if TEMA_RE.match(l) and not started:
            started = True
            continue
        if started:
            if l.lower().startswith("auxiliar administrativo"):
                break
            out.append(l)
    t = " ".join(out)
    if t.isupper():
        t = t.capitalize()
    return re.sub(r"\s+", " ", t).strip()


def detect_topic(folder: Path, docs: list[Path]) -> TopicInfo | None:
    """Determina el tema de una carpeta a partir de la portada del temario y de los nombres."""
    theory = [d for d in docs if classify_name(d.name) == "otro"]
    for d in theory:
        big, full = cover_of(d)
        m = TEMA_RE.search(big) or TEMA_RE.search(full)
        if m:
            anexo = "II" if (ANEXO2_RE.search(big) or ANEXO2_RE.search(d.name)) else "I"
            t = TopicInfo(topic_id(anexo, int(m.group(1))), anexo, int(m.group(1)), folder=rel(folder))
            return t
    for d in docs:
        m = TEMA_RE.search(d.stem)
        if m:
            anexo = "II" if ANEXO2_RE.search(d.stem) else "I"
            return TopicInfo(topic_id(anexo, int(m.group(1))), anexo, int(m.group(1)), folder=rel(folder))
    m = TEMA_RE.search(folder.name)
    if m:
        return TopicInfo(topic_id("I", int(m.group(1))), "I", int(m.group(1)), folder=rel(folder))
    return None


DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})(?:-\d{2,4})?")


def _dates(p: Path) -> set[tuple[int, int]]:
    return {(int(a), int(b)) for a, b in DATE_RE.findall(p.stem)}


PREFIX_RE = re.compile(r"^(\d{1,2})\s*\.")  # nº de orden de las prácticas («5.Test …» ↔ «5.Soluciones …»)


def pair_solution(test: Path, sols: list[Path]) -> Path | None:
    if not sols:
        return None
    m = PREFIX_RE.match(test.name)
    if m:
        same = [s for s in sols if (PREFIX_RE.match(s.name) or [None, None])[1] == m.group(1)]
        return same[0] if len(same) == 1 else None
    if _dates(test):  # test de clase con fecha: solo su solucionario de la misma fecha
        sols = [s for s in sols if _dates(s) & _dates(test)]
        if not sols:
            return None
    if len(sols) == 1:
        return sols[0]
    parte = lambda p: re.findall(r"parte \d+", normalize(p.stem))  # «Parte 2» solo con su solucionario
    sols = [s for s in sols if parte(s) == parte(test)] or sols
    key = normalize(test.stem.replace("Test", ""))
    return max(sols, key=lambda s: difflib.SequenceMatcher(None, key, normalize(s.stem.replace("Soluciones", ""))).ratio())


# --------------------------------------------------------------------------- importación principal

def run(verbose: bool = True) -> dict:
    t0 = datetime.now()
    rep = Report()
    files = list(iter_files())
    by_folder: dict[Path, list[Path]] = defaultdict(list)
    for f in files:
        by_folder[f.parent].append(f)

    topics: dict[str, TopicInfo] = {}
    doc_rows: list[tuple] = []
    tests: list[dict] = []            # {id, topic, doc, sol_doc, name, qs:[ParsedQuestion], sols}
    theory_docs: list[tuple[str, Path]] = []
    esquemas: list[tuple[str, str, int, str]] = []
    other_docs: list[tuple[str, Path]] = []

    def add_doc(p: Path, kind: str, tid: str | None):
        pages = pages_of(p) if p.suffix.lower() in DOC_EXT else 1
        doc_rows.append((rel(p), p.name, kind, tid, pages, file_hash(p), p.stat().st_size))
        rep.documents.append({"documento": rel(p), "tipo": kind, "tema": tid, "paginas": pages})

    folder_topics = CATALOG.get("carpetas_tema", {})
    ignored = {normalize(x) for x in CATALOG.get("ignorar_documentos", [])}
    seen_hashes: dict[str, str] = {}

    # --- 1. carpetas con documentos
    for folder, fl in sorted(by_folder.items()):
        docs = [f for f in fl if f.suffix.lower() in DOC_EXT and normalize(rel(f)) not in ignored]
        for d in list(docs):
            h = file_hash(d)
            if h in seen_hashes:  # copia idéntica de un documento ya importado (p. ej. Caso practico ↔ PRACTICAS)
                docs.remove(d)
                rep.issue("documento_duplicado", rel(d), f"Copia idéntica de {seen_hashes[h]}; se importa solo una vez")
            else:
                seen_hashes[h] = rel(d)
        for d in [d for d in docs if d.suffix.lower() == ".pdf" and pages_of(d) == 0]:
            docs.remove(d)  # PDF dañado o a medio copiar: se omite sin abortar la importación
            rep.issue("documento_ilegible", rel(d), "PDF sin páginas legibles (archivo dañado o incompleto); se omite")
        imgs = [f for f in fl if f.suffix.lower() in IMG_EXT]
        if docs:
            ft = folder_topics.get(rel(folder))
            tinfo = TopicInfo(ft, "-", 99, folder=rel(folder)) if ft else detect_topic(folder, docs)
            if tinfo is None:
                # carpeta sin número de tema (p. ej. "Caso practico")
                has_tests = any(len(parse_questions(lines_of(d))) >= 5 for d in docs if classify_name(d.name) != "equivalencias")
                if has_tests:
                    tinfo = TopicInfo("CP" if "caso" in normalize(folder.name) else "X-" + normalize(folder.name).replace(" ", "-")[:20],
                                      "-", 99, folder=rel(folder))
            if tinfo:
                tinfo = topics.setdefault(tinfo.id, tinfo)
            tid = tinfo.id if tinfo else None
            sols = [d for d in docs if classify_name(d.name) == "soluciones"]
            for d in docs:
                kind = classify_name(d.name)
                if kind == "soluciones":
                    add_doc(d, "soluciones", tid)
                    continue
                if kind == "equivalencias":
                    add_doc(d, "equivalencias", None)
                    other_docs.append(("equivalencias", d))
                    continue
                lines = lines_of(d)
                qs = parse_questions(lines)
                good = [q for q in qs if len(q.options) >= 2]
                # en Prácticas, un «Test» sin preguntas tipo test es el supuesto de desarrollo
                if len(good) >= 5 or (kind == "test" and not (tid == "CP" and not good)):
                    sol = pair_solution(d, sols)
                    add_doc(d, "test", tid)
                    tests.append({"topic": tid, "doc": d, "sol_doc": sol, "qs": qs,
                                  "sols": parse_solutions(lines_of(sol)) if sol else []})
                    if sol is None:
                        rep.issue("sin_solucionario", rel(d), f"El test «{d.name}» no tiene solucionario: sus {len(qs)} preguntas quedan pendientes de revisión.")
                elif tid and tid != "CP" and TEMA_RE.search(cover_of(d)[0] + " " + d.stem):
                    add_doc(d, "teoria", tid)
                    theory_docs.append((tid, d))
                    big, full = cover_of(d)
                    ttl = cover_title(full)
                    if ttl:
                        topics[tid].titles.append((d.stem.lower(), ttl))
                else:
                    add_doc(d, "supuesto" if tid == "CP" else "documento", tid)
                    other_docs.append(("supuesto", d))
        if imgs:
            r = rel(folder)
            flat = CATALOG.get("esquemas_flat", {}).get(r)
            if flat:
                for t_id, ranges in flat.items():
                    for a, b, label in ranges:
                        for i in range(a, b + 1):
                            p = folder / f"{i}.png"
                            if p.exists():
                                esquemas.append((t_id, rel(p), i, label))
                                add_doc(p, "esquema", t_id)
                for p in imgs:
                    if rel(p) not in {e[1] for e in esquemas}:
                        rep.issue("esquema_sin_tema", rel(p), "Imagen sin tema asignado en core/catalog.json")
                        add_doc(p, "esquema", None)
            else:
                m = TEMA_RE.search(folder.name)
                anexo = "II" if ANEXO2_RE.search(r) else "I"
                t_id = topic_id(anexo, int(m.group(1))) if m else None
                for p in sorted(imgs, key=lambda x: (int(re.sub(r"\D", "", x.stem) or 0), x.stem)):
                    esquemas.append((t_id, rel(p), int(re.sub(r"\D", "", p.stem) or 0), ""))
                    add_doc(p, "esquema", t_id)

    # --- 2. preguntas, verificación con soluciones
    questions: dict[str, dict] = {}
    sources: list[tuple] = []
    test_rows: list[tuple] = []
    for tpos, t in enumerate(sorted(tests, key=lambda x: (x["topic"] or "", x["doc"].name))):
        doc_id = rel(t["doc"])
        test_id = "T:" + doc_id
        sol_id = rel(t["sol_doc"]) if t["sol_doc"] else None
        sols = {s.number: s for s in t["sols"]}
        if t["sol_doc"] and len(t["sols"]) != len(t["qs"]):
            rep.issue("recuento_distinto", doc_id, f"El test tiene {len(t['qs'])} preguntas y el solucionario {len(t['sols'])} respuestas.")
        n_ver = 0
        for q in t["qs"]:
            qid = question_uid(q.stem, q.options)
            status, reason, letter, just, spage = "verificada", "", None, "", None
            s: ParsedSolution | None = sols.get(q.number)
            if q.issues:
                status, reason = "pendiente", "; ".join(q.issues)
            elif not t["sol_doc"]:
                status, reason = "pendiente", "Sin solucionario oficial en los documentos"
            elif s is None:
                status, reason = "pendiente", f"El solucionario no contiene la pregunta {q.number}"
            else:
                letter, just, spage = s.letter, s.justification, s.page
                idx = LETTERS.index(s.letter) if s.letter in LETTERS else 99
                if idx >= len(q.options):
                    status, reason = "contradiccion", f"El solucionario indica «{s.letter.upper()}», que no existe entre las opciones"
                elif s.option_text:
                    # el solucionario repite el texto de la opción: comprobamos que coincide
                    sol_n, opt_n = normalize(s.option_text), normalize(q.options[idx])
                    ratio = difflib.SequenceMatcher(None, sol_n, opt_n).ratio()
                    extra = sol_n[len(opt_n):] if sol_n.startswith(opt_n) else ""
                    if extra and re.search(r"tambien|valida|correcta", extra):
                        status = "contradiccion"
                        reason = (f"Pregunta ambigua: el solucionario marca la {s.letter.upper()} pero añade "
                                  f"«{s.option_text[len(q.options[idx]):].strip()}»")
                    elif sol_n.startswith(opt_n):
                        pass
                    elif ratio < 0.8:
                        best = max(range(len(q.options)), key=lambda i: difflib.SequenceMatcher(None, normalize(s.option_text), normalize(q.options[i])).ratio())
                        status = "contradiccion"
                        reason = (f"El solucionario indica la letra {s.letter.upper()} pero su texto coincide con la opción "
                                  f"{LETTERS[best].upper()}")
            if status != "verificada":
                rep.issue(status, doc_id, f"Pregunta {q.number}: {reason}", qid)
            else:
                n_ver += 1
            if qid in questions:
                prev = questions[qid]
                rep.issue("duplicado_exacto", doc_id, f"Pregunta {q.number} idéntica a otra ya importada ({prev['source_doc_id']} nº {prev['source_number']})", qid)
                if prev["status"] == "verificada" and status == "verificada" and prev["correct_letter"] != letter:
                    prev["status"] = "contradiccion"
                    prev["status_reason"] = "La misma pregunta tiene soluciones distintas en dos solucionarios"
                    rep.issue("contradiccion", doc_id, prev["status_reason"], qid)
                elif prev["status"] != "verificada" and status == "verificada":
                    prev.update(correct_letter=letter, status=status, status_reason="", official_justification=just,
                                solution_doc_id=sol_id, solution_page=spage)
            else:
                questions[qid] = dict(id=qid, topic_id=t["topic"], stem=q.stem, options=q.options, correct_letter=letter,
                                      status=status, status_reason=reason, official_justification=just,
                                      solution_doc_id=sol_id, solution_page=spage, source_doc_id=doc_id,
                                      source_page=q.page, source_number=q.number, dup_group=qid)
            sources.append((qid, test_id, q.number, doc_id, q.page, q.number))
        name = t["doc"].stem
        test_rows.append((test_id, t["topic"], name, doc_id, sol_id, len(t["qs"]), n_ver, tpos))

    # --- 3. duplicados aproximados (mismo enunciado con redacción casi idéntica)
    qlist = list(questions.values())
    norm = {q["id"]: normalize(q["stem"]) for q in qlist}
    toks = {k: set(v.split()) for k, v in norm.items()}
    parent = {q["id"]: q["id"] for q in qlist}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def correct_text(q):
        if not q["correct_letter"]:
            return None
        i = LETTERS.index(q["correct_letter"])
        return normalize(q["options"][i]) if i < len(q["options"]) else None

    near_pairs = 0
    for i, a in enumerate(qlist):
        for b in qlist[i + 1:]:
            ta, tb = toks[a["id"]], toks[b["id"]]
            if not ta or not tb or len(ta & tb) / len(ta | tb) < 0.6:
                continue
            r = difflib.SequenceMatcher(None, norm[a["id"]], norm[b["id"]]).ratio()
            if r < 0.88:
                continue
            ca, cb = correct_text(a), correct_text(b)
            opts_a = {normalize(o) for o in a["options"]}
            opts_b = {normalize(o) for o in b["options"]}
            same_opts = len(opts_a & opts_b) >= min(len(opts_a), len(opts_b)) - 1
            if ca and cb and same_opts and difflib.SequenceMatcher(None, ca, cb).ratio() < 0.8 and ca not in opts_b - {cb}:
                # mismo enunciado y mismas opciones pero distinta respuesta oficial
                for q in (a, b):
                    q["status"] = "contradiccion"
                    q["status_reason"] = "Pregunta casi idéntica en otro test con distinta solución oficial"
                rep.issue("contradiccion", a["source_doc_id"], f"«{a['stem'][:80]}…» tiene solución distinta en {b['source_doc_id']}", a["id"])
                continue
            if same_opts or (ca and cb and ca == cb):
                parent[find(b["id"])] = find(a["id"])
                near_pairs += 1
                rep.issue("posible_duplicado", b["source_doc_id"],
                          f"Pregunta {b['source_number']} muy similar a {a['source_doc_id']} nº {a['source_number']}", b["id"])
    for q in qlist:
        q["dup_group"] = find(q["id"])

    # claves de respuesta verificadas manualmente por el usuario (pantalla «Banco de preguntas»)
    try:
        ukeys = {r["question_id"]: r for r in db.query("SELECT * FROM user_answer_keys")}
    except Exception:
        ukeys = {}
    for qid, r in ukeys.items():
        q = questions.get(qid)
        if q and q["status"] == "pendiente":
            q.update(correct_letter=r["letter"], status="verificada_usuario",
                     status_reason=f"Solución introducida por el usuario ({r['source']})")

    # erratas del solucionario corregidas según la norma (core/catalog.json → «correcciones»)
    for qid, cfix in CATALOG.get("correcciones", {}).items():
        q = questions.get(qid)
        if q:
            q.update(correct_letter=cfix["letra"], official_justification=cfix["motivo"])

    # correcciones del solucionario identificadas por el enunciado (no por el número, que cambia al unificar test)
    for cfix in CATALOG.get("correcciones_enunciado", []):
        frag = normalize(cfix["enunciado"])
        hits = [q for q in qlist if frag in normalize(q["stem"])]
        if len(hits) != 1:
            rep.issue("correccion_no_aplicada", None, f"La corrección «{cfix['enunciado'][:60]}…» coincide con {len(hits)} preguntas")
            continue
        q = hits[0]
        if q["correct_letter"] != cfix["letra"]:
            q.update(correct_letter=cfix["letra"], official_justification=f"{cfix['motivo']} (corrección del solucionario)",
                     status="verificada", status_reason="")
        q["status_reason"] = q["status_reason"] or f"Respuesta comprobada: {cfix['motivo']}"

    # test combinados (varios documentos en un único test, sin preguntas repetidas)
    combined_ids: set[str] = set()
    test_rows_all = list(test_rows)
    for comb in CATALOG.get("test_combinados", []):
        docs_c = [d for d in comb["documentos"] if any(r[3] == d for r in test_rows)]
        if not docs_c:
            continue
        cid_test = "T:" + comb["nombre"]
        combined_ids.add(cid_test)
        old_ids = {"T:" + d for d in docs_c}
        first = next(r for r in test_rows if r[3] == docs_c[0])
        by_test = defaultdict(list)
        for srow in sources:
            if srow[1] in old_ids:
                by_test[srow[1]].append(srow)
        t10 = re.compile(comb.get("clasificar", {}).get("patron", r"$^"), re.I)
        chosen, groups = [], set()
        for d in docs_c:
            for srow in sorted(by_test["T:" + d], key=lambda r: r[2]):
                q = questions[srow[0]]
                if q["dup_group"] in groups or any(srow[0] == c[0] for c in chosen):
                    continue
                twin = next((c for c in chosen if _near_same(questions[c[0]], q)), None)
                if twin:
                    rep.issue("duplicado_unificado", srow[3], f"Pregunta {srow[5]} repetida en {comb['nombre']} "
                              f"(igual que {twin[3]} nº {twin[5]}); se conserva una sola", srow[0])
                    continue
                groups.add(q["dup_group"])
                chosen.append(srow)
        for srow in chosen:  # tema de cada pregunta según su contenido (p. ej. LPRL → Tema 10)
            q = questions[srow[0]]
            if "clasificar" in comb and srow[3] in comb["clasificar"].get("documentos", comb["documentos"]):
                blob = " ".join([q["stem"], *q["options"], q["official_justification"] or ""])
                q["topic_id"] = comb["clasificar"]["tema_si"] if t10.search(blob) else comb["clasificar"]["tema_no"]
        sources = [r for r in sources if r[1] not in old_ids]
        sources += [(r[0], cid_test, pos, r[3], r[4], r[5]) for pos, r in enumerate(chosen, 1)]
        n_ver = sum(1 for r in chosen if questions[r[0]]["status"].startswith("verificada"))
        test_rows = [r for r in test_rows if r[0] not in old_ids]
        test_rows.append((cid_test, comb.get("tema", first[1]), comb["nombre"], first[3], first[4], len(chosen), n_ver,
                          min(r[7] for r in test_rows_all if r[0] in old_ids)))
    test_rows.sort(key=lambda r: r[7])

    # --- 4. teoría: apartados y párrafos
    section_rows, chunk_rows = [], []
    sid = cid = 0
    theory_docs.sort(key=lambda x: (x[0], x[1].stem.lower()))  # «Tema 1» antes que «Tema 1 - Parte 2»
    for tid, d in theory_docs:
        for ordn, s in enumerate(parse_theory(lines_of(d))):
            sid += 1
            section_rows.append((sid, tid, rel(d), ordn, s.title, s.level, s.page, s.text))
            for p in s.paragraphs:
                if len(p.text) < 25:
                    continue
                cid += 1
                chunk_rows.append((cid, sid, tid, rel(d), p.page, p.text))

    # --- 5. vínculo pregunta ↔ teoría (BM25 limitado a los temas donde aparece la pregunta)
    q_topics: dict[str, set] = defaultdict(set)
    test_topic = {r[0]: r[1] for r in test_rows}
    for qid, test_id, *_ in sources:
        q_topics[qid].add(questions[qid]["topic_id"] if test_id in combined_ids else test_topic[test_id])
    theory_links = []
    if chunk_rows:
        sec_title = {s[0]: s[4] for s in section_rows}
        bm = BM25([f"{sec_title[c[1]]} {c[5]}" for c in chunk_rows])
        by_topic: dict[str, set] = defaultdict(set)
        for i, c in enumerate(chunk_rows):
            by_topic[c[2]].add(i)
        for q in qlist:
            allowed = set().union(*(by_topic.get(t, set()) for t in q_topics[q["id"]])) or None
            if q["correct_letter"] and LETTERS.index(q["correct_letter"]) < len(q["options"]):
                qtext = f"{q['stem']} {q['options'][LETTERS.index(q['correct_letter'])]} {q['official_justification']}"
            else:
                qtext = q["stem"] + " " + " ".join(q["options"])
            top = bm.top(qtext, 3, allowed) or bm.top(q["stem"] + " " + " ".join(q["options"]), 3, allowed)
            for rank, (i, sc) in enumerate(top):
                theory_links.append((q["id"], chunk_rows[i][0], rank, round(sc, 3)))

    # --- 6. temas: títulos
    topic_rows = []
    for t in topics.values():
        if t.id == "CP":
            t.title = "Prácticas de clase: test y supuesto de desarrollo"
        else:
            t.title = " · ".join(dict.fromkeys(ttl for _, ttl in sorted(t.titles))) or t.id
        short = CATALOG.get("short_names", {}).get(t.id) or t.title[:60]
        order = (0 if t.anexo == "I" else 100 if t.anexo == "II" else 900) + t.number
        topic_rows.append((t.id, t.anexo, t.number, short, t.title, order, t.folder))

    # --- 7. guardar (transacción única: si algo falla, el banco anterior se conserva)
    with db.tx() as con:
        for tbl in db.BANK_TABLES:
            con.execute(f"DELETE FROM {tbl}")
        con.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?)", doc_rows)
        con.executemany("INSERT INTO topics VALUES (?,?,?,?,?,?,?)", topic_rows)
        con.executemany("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?)", section_rows)
        con.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)", chunk_rows)
        con.executemany("INSERT INTO tests VALUES (?,?,?,?,?,?,?,?)", test_rows)
        con.executemany(
            "INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(q["id"], q["topic_id"], q["stem"], json.dumps(q["options"], ensure_ascii=False), q["correct_letter"],
              q["status"], q["status_reason"], q["official_justification"], q["solution_doc_id"], q["solution_page"],
              q["source_doc_id"], q["source_page"], q["source_number"], q["dup_group"]) for q in qlist])
        con.executemany("INSERT OR REPLACE INTO question_sources VALUES (?,?,?,?,?,?)", sources)
        con.executemany("INSERT INTO question_theory VALUES (?,?,?,?)", theory_links)
        con.executemany("INSERT INTO esquemas(topic_id,path,ord,label) VALUES (?,?,?,?)", esquemas)
        con.executemany("INSERT INTO issues(kind,doc_id,question_id,detail) VALUES (?,?,?,?)",
                        [(i["kind"], i["doc"], i["question_id"], i["detail"]) for i in rep.issues])

    inv = build_inventory(rep, started=t0)
    if verbose:
        print(inventory_markdown(inv))
    return inv


def _near_same(a: dict, b: dict) -> bool:
    """Misma pregunta con pequeñas diferencias de redacción: enunciado casi igual y misma respuesta correcta."""
    sa, sb = normalize(a["stem"]), normalize(b["stem"])
    r = difflib.SequenceMatcher(None, sa, sb).ratio()
    if r >= 0.9:
        return True
    ca = a["options"][LETTERS.index(a["correct_letter"])] if a["correct_letter"] else ""
    cb = b["options"][LETTERS.index(b["correct_letter"])] if b["correct_letter"] else ""
    return r >= 0.75 and bool(ca) and difflib.SequenceMatcher(None, normalize(ca), normalize(cb)).ratio() >= 0.85


# --------------------------------------------------------------------------- inventario

def build_inventory(rep: Report | None = None, started: datetime | None = None) -> dict:
    q = db.query
    topics = q("SELECT * FROM topics ORDER BY sort_order")
    per_topic = []
    for t in topics:
        row = q("""SELECT COUNT(DISTINCT qs.question_id) n,
                   COUNT(DISTINCT CASE WHEN qq.status LIKE 'verificada%' THEN qs.question_id END) v
                   FROM question_sources qs JOIN tests ts ON ts.id=qs.test_id JOIN questions qq ON qq.id=qs.question_id
                   WHERE ts.topic_id=?""", (t["id"],))[0]
        per_topic.append({"tema": t["id"], "nombre": t["short_name"], "preguntas": row["n"], "verificadas": row["v"],
                          "apartados_teoria": db.scalar("SELECT COUNT(*) FROM sections WHERE topic_id=?", (t["id"],)),
                          "esquemas": db.scalar("SELECT COUNT(*) FROM esquemas WHERE topic_id=?", (t["id"],))})
    total_occ = db.scalar("SELECT COUNT(*) FROM question_sources", default=0)
    inv = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "temas_detectados": db.scalar("SELECT COUNT(*) FROM topics WHERE id!='CP'"),
        "documentos": db.scalar("SELECT COUNT(*) FROM documents"),
        "documentos_por_tipo": {r["kind"]: r["n"] for r in q("SELECT kind, COUNT(*) n FROM documents GROUP BY kind")},
        "test_originales": db.scalar("SELECT COUNT(*) FROM tests"),
        "preguntas_totales": total_occ,
        "preguntas_unicas": db.scalar("SELECT COUNT(*) FROM questions"),
        "grupos_sin_duplicados_aprox": db.scalar("SELECT COUNT(DISTINCT dup_group) FROM questions"),
        "preguntas_verificadas": db.scalar("SELECT COUNT(*) FROM questions WHERE status LIKE 'verificada%'"),
        "preguntas_pendientes": db.scalar("SELECT COUNT(*) FROM questions WHERE status='pendiente'"),
        "preguntas_con_contradiccion": db.scalar("SELECT COUNT(*) FROM questions WHERE status='contradiccion'"),
        "apartados_teoria": db.scalar("SELECT COUNT(*) FROM sections"),
        "esquemas": db.scalar("SELECT COUNT(*) FROM esquemas"),
        "por_tema": per_topic,
        "test": [dict(r) for r in q("SELECT id, topic_id, name, doc_id, solution_doc_id, n_questions, n_verified FROM tests ORDER BY ord")],
        "incidencias": [dict(r) for r in q("SELECT kind, doc_id, question_id, detail FROM issues ORDER BY id")],
        "documentos_detalle": [dict(r) for r in q("SELECT id, kind, topic_id, pages FROM documents ORDER BY id")],
    }
    config.INVENTORY_JSON.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")
    config.INVENTORY_MD.write_text(inventory_markdown(inv), encoding="utf-8")
    return inv


def inventory_markdown(inv: dict) -> str:
    L = ["# Inventario del material de estudio", "", f"Generado: {inv['generado']}", "",
         "| Concepto | Valor |", "|---|---|",
         f"| Temas detectados | {inv['temas_detectados']} |",
         f"| Documentos | {inv['documentos']} ({', '.join(f'{k}: {v}' for k, v in inv['documentos_por_tipo'].items())}) |",
         f"| Test originales | {inv['test_originales']} |",
         f"| Preguntas totales (apariciones) | {inv['preguntas_totales']} |",
         f"| Preguntas únicas | {inv['preguntas_unicas']} |",
         f"| Preguntas con respuesta verificada | {inv['preguntas_verificadas']} |",
         f"| Preguntas pendientes de revisión | {inv['preguntas_pendientes']} |",
         f"| Preguntas con contradicción | {inv['preguntas_con_contradiccion']} |",
         f"| Apartados de teoría | {inv['apartados_teoria']} |",
         f"| Esquemas (imágenes) | {inv['esquemas']} |", "",
         "## Preguntas por tema", "", "| Tema | Nombre | Preguntas | Verificadas | Apartados | Esquemas |", "|---|---|---|---|---|---|"]
    for t in inv["por_tema"]:
        L.append(f"| {t['tema']} | {t['nombre']} | {t['preguntas']} | {t['verificadas']} | {t['apartados_teoria']} | {t['esquemas']} |")
    L += ["", "## Test originales", "", "| Test | Tema | Preguntas | Verificadas | Solucionario |", "|---|---|---|---|---|"]
    for t in inv["test"]:
        L.append(f"| {t['doc_id']} | {t['topic_id']} | {t['n_questions']} | {t['n_verified']} | {t['solution_doc_id'] or '—'} |")
    L += ["", "## Incidencias", ""]
    kinds = defaultdict(list)
    for i in inv["incidencias"]:
        kinds[i["kind"]].append(i)
    for k, items in kinds.items():
        L.append(f"### {k} ({len(items)})")
        for i in items[:60]:
            L.append(f"- `{i['doc_id']}` — {i['detail']}")
        if len(items) > 60:
            L.append(f"- … y {len(items) - 60} más")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run()
