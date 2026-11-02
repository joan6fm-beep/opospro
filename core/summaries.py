"""Resúmenes EXTRACTIVOS: se seleccionan frases literales del temario (con su página).

No se reescribe ni se añade contenido: cada frase mostrada existe tal cual en el documento.
La importancia de una frase se estima con:
  * términos que aparecen en las preguntas y respuestas oficiales del tema (lo que se pregunta),
  * referencias a artículos, plazos, cifras y mayorías,
  * expresiones definitorias («se entiende por», «es», «corresponde», «deberá»…).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from . import bank, db, srs
from .search import tokenize

ABBR = ("art", "arts", "núm", "pág", "apdo", "sr", "sra", "etc", "ej", "vid", "ss", "cfr", "aprox", "dcho", "lpac", "lbrl", "ce")
SIGNAL_RE = re.compile(r"(art[íi]culo|art\.|plazo|d[íi]as|mes(es)?|años?|mayor[íi]a|absoluta|simple|\d+)", re.I)
DEF_RE = re.compile(r"(se entiende por|se define|se considera|es (el|la|un|una)\b|consiste en|corresponde|deber[áa]n?|podr[áa]n?|"
                    r"no podr[áa]|en todo caso|salvo|exclusiv)", re.I)


@dataclass
class Sentence:
    text: str
    page: int
    doc_id: str
    section_id: int
    section_title: str
    score: float = 0.0


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;:!?])\s+(?=[A-ZÁÉÍÓÚÑ«“\"(•\-–\d])", text)
    out: list[str] = []
    for p in parts:
        if out and re.search(r"\b(" + "|".join(ABBR) + r")\.$", out[-1], re.I):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return [s.strip(" •") for s in out if len(s.strip()) > 30]


def topic_keywords(tid: str) -> Counter:
    ids = bank.question_ids_for_topics([tid])
    qs = bank.get_questions(ids)
    c: Counter = Counter()
    for q in qs.values():
        c.update(tokenize(q.stem))
        c.update(tokenize(q.correct_text) * 2)
        c.update(tokenize(q.justification))
    return c


def _sentences_for_sections(sections: list[dict]) -> list[Sentence]:
    out = []
    for s in sections:
        for ch in db.query("SELECT * FROM chunks WHERE section_id=? ORDER BY id", (s["id"],)):
            for sent in split_sentences(ch["text"]):
                out.append(Sentence(sent, ch["page"], ch["doc_id"], s["id"], s["title"]))
    return out


def score_sentences(sents: list[Sentence], kw: Counter) -> None:
    total = sum(kw.values()) or 1
    for s in sents:
        toks = tokenize(s.text)
        if not toks:
            continue
        kscore = sum(min(kw.get(t, 0), 12) for t in set(toks)) / (len(set(toks)) ** 0.5)
        sig = len(SIGNAL_RE.findall(s.text)) * 0.8
        dfn = 2.0 if DEF_RE.search(s.text) else 0.0
        length_pen = 0.0 if 60 <= len(s.text) <= 380 else -2.0
        s.score = kscore / max(total / 2000, 1) + sig + dfn + length_pen


def summary_by_section(tid: str, per_section: int = 3, section_ids: list[int] | None = None) -> list[dict]:
    """Para cada apartado, sus frases clave en orden de aparición."""
    secs = bank.sections_for_topic(tid)
    if section_ids:
        secs = [s for s in secs if s["id"] in section_ids]
    kw = topic_keywords(tid)
    sents = _sentences_for_sections(secs)
    score_sentences(sents, kw)
    by_sec: dict[int, list[Sentence]] = defaultdict(list)
    for s in sents:
        by_sec[s.section_id].append(s)
    out = []
    for s in secs:
        cand = by_sec.get(s["id"], [])
        top = sorted(cand, key=lambda x: -x.score)[:per_section]
        top.sort(key=lambda x: cand.index(x))
        out.append({"section": s, "sentences": top})
    return out


def quick_summary(tid: str, n: int = 20) -> list[Sentence]:
    secs = bank.sections_for_topic(tid)
    sents = _sentences_for_sections(secs)
    score_sentences(sents, topic_keywords(tid))
    seen, out = set(), []
    for s in sorted(sents, key=lambda x: -x.score):
        key = s.text[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= n:
            break
    order = {id(s): i for i, s in enumerate(sents)}
    return sorted(out, key=lambda s: order[id(s)])


def outline(tid: str) -> list[dict]:
    """Esquema jerárquico de apartados con nº de preguntas vinculadas a cada uno."""
    secs = bank.sections_for_topic(tid)
    counts = {r[0]: r[1] for r in db.query("""SELECT c.section_id, COUNT(DISTINCT qt.question_id) FROM question_theory qt
                                               JOIN chunks c ON c.id=qt.chunk_id WHERE qt.rank=0 AND c.topic_id=? GROUP BY c.section_id""", (tid,))}
    return [{**s, "n_questions": counts.get(s["id"], 0)} for s in secs]


def key_terms(tid: str, n: int = 25) -> list[tuple[str, int]]:
    """Términos y referencias normativas que más se repiten en las preguntas del tema (literal)."""
    ids = bank.question_ids_for_topics([tid])
    qs = bank.get_questions(ids)
    refs: Counter = Counter()
    for q in qs.values():
        text = f"{q.stem} {q.correct_text} {q.justification}"
        for m in re.finditer(r"\b(?:art(?:ículo|s?\.)\s*\d+(?:\.\d+)?(?:\.[a-z]\))?\s*(?:de la |del )?[A-Z]{2,}[A-Za-z]*)", text):
            refs[re.sub(r"\s+", " ", m.group(0)).strip()] += 1
    return refs.most_common(n)


def error_patterns(topic_ids: list[str] | None = None, min_fails: int = 2) -> list[dict]:
    """Agrupa las preguntas falladas por apartado del temario.

    Un apartado con `min_fails` o más preguntas falladas distintas se marca como patrón de error.
    """
    rows = db.query("SELECT * FROM review_state WHERE n_wrong>0")
    if not rows:
        return []
    states = {r["question_id"]: dict(r) for r in rows}
    allowed = set(bank.question_ids_for_topics(topic_ids)) if topic_ids else None
    qids = [q for q in states if allowed is None or q in allowed]
    if not qids:
        return []
    links = db.query(f"""SELECT qt.question_id, c.section_id, s.title, s.topic_id, s.doc_id, s.page, qt.score
                         FROM question_theory qt JOIN chunks c ON c.id=qt.chunk_id JOIN sections s ON s.id=c.section_id
                         WHERE qt.rank=0 AND qt.question_id IN ({','.join('?' * len(qids))})""", qids)
    groups: dict[int, dict] = {}
    for l in links:
        g = groups.setdefault(l["section_id"], {"section_id": l["section_id"], "title": l["title"], "topic_id": l["topic_id"],
                                                "doc_id": l["doc_id"], "page": l["page"], "questions": [], "fails": 0,
                                                "still_failing": 0})
        st = states[l["question_id"]]
        g["questions"].append(l["question_id"])
        g["fails"] += st["n_wrong"]
        g["still_failing"] += 1 if st["last_result"] == 0 else 0
    out = sorted(groups.values(), key=lambda g: (-len(g["questions"]), -g["fails"]))
    for g in out:
        g["pattern"] = len(g["questions"]) >= min_fails
    return out


def section_text(section_id: int) -> dict | None:
    r = db.query_one("SELECT * FROM sections WHERE id=?", (section_id,))
    return dict(r) if r else None


def log_study_time(topic_id: str | None, seconds: int) -> None:
    if seconds <= 0:
        return
    db.execute("INSERT INTO activity(kind,topic_id,day,seconds,ts) VALUES ('estudio',?,?,?,?)",
               (topic_id, srs.now().date().isoformat(), int(seconds), srs.iso(srs.now())))
