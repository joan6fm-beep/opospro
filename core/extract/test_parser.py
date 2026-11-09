"""Extracción de preguntas tipo test y de solucionarios oficiales.

No se infiere nada: si una pregunta no tiene opciones completas o su solución no aparece
en el solucionario, queda marcada como pendiente de revisión.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .pdf_reader import Line

Q_NUM_RE = re.compile(r"^(\d{1,3})\s*[.\-–)]\s+(.*)$")
Q_WORD_RE = re.compile(r"^PREGUNTA\s+(\d{1,3})\s*[:.]?\s*(.*)$", re.I)
SOL_GRID_RE = re.compile(r"^(\d{1,3})\s*\.\s*([a-dA-D])$")
OPT_RE = re.compile(r"^([a-hA-H])\s*\)\s*(.*)$")
LETTERS = "abcdefgh"


@dataclass
class ParsedQuestion:
    number: int
    stem: str
    options: list[str]
    page: int
    issues: list[str] = field(default_factory=list)


@dataclass
class ParsedSolution:
    number: int
    letter: str
    option_text: str = ""      # texto de la opción indicado en el solucionario (si lo incluye)
    justification: str = ""
    page: int = 0


def _join(a: str, b: str) -> str:
    if not a:
        return b
    if a.endswith("-") and not a.endswith(" -"):
        return a[:-1] + b
    return a + " " + b


def parse_questions(lines: list[Line]) -> list[ParsedQuestion]:
    qs: list[ParsedQuestion] = []
    cur: ParsedQuestion | None = None
    expected = 1
    for ln in lines:
        t = ln.text
        mq = Q_WORD_RE.match(t) or Q_NUM_RE.match(t)
        if mq and int(mq.group(1)) == expected and (cur is None or len(cur.options) >= 2):
            cur = ParsedQuestion(int(mq.group(1)), mq.group(2).strip(), [], ln.page)
            qs.append(cur)
            expected += 1
            continue
        if cur is None:
            continue  # texto de portada / título
        mo = OPT_RE.match(t)
        next_letter = LETTERS[len(cur.options)] if len(cur.options) < len(LETTERS) else None
        if mo and mo.group(1).lower() == next_letter:
            cur.options.append(mo.group(2).strip())
            continue
        if (mo and next_letter and len(cur.options) < 4 and mo.group(1).lower() < next_letter
                and cur.options[-1].rstrip().endswith(".") and mo.group(2)[:1].isupper()):
            # errata del documento: letra repetida («a) b) a) c)»); es la opción siguiente
            cur.options.append(mo.group(2).strip())
            continue
        if cur.options:
            cur.options[-1] = _join(cur.options[-1], t)
        else:
            cur.stem = _join(cur.stem, t)
    for q in qs:
        q.stem = q.stem.strip()
        q.options = [o.strip() for o in q.options]
        if len(q.options) < 2:
            q.issues.append("Menos de 2 opciones detectadas")
        if not q.stem:
            q.issues.append("Enunciado vacío")
        if any(not o for o in q.options):
            q.issues.append("Alguna opción vacía")
    return qs


SOL_A_RE = re.compile(r"^(\d{1,3})\s*\.\s*([A-Ha-h])\s*(?:[—–\-:)]\s*(.*))?$")
SOL_B_HEAD_RE = re.compile(r"^Pregunta\s+(\d{1,3})\s*$", re.I)
SOL_B_ANS_RE = re.compile(r"^Respuesta correcta\s*:\s*([A-Ha-h])\s*\)\s*(.*)$", re.I)
SOL_B_JUST_RE = re.compile(r"^Justificaci[óo]n(?:\s+jur[íi]dica)?\s*:\s*(.*)$", re.I)
# «1. Pregunta 1: Opción c» (Soluciones Test Tema 7 y 10)
SOL_C_RE = re.compile(r"^(\d{1,3})\s*\.\s*Pregunta\s+\d{1,3}\s*:\s*Opci[óo]n\s+([A-Ha-h])\b\s*(.*)$", re.I)


def parse_solutions(lines: list[Line]) -> list[ParsedSolution]:
    sols: list[ParsedSolution] = []
    cur: ParsedSolution | None = None
    mode = None  # 'opt' | 'just'
    expected = 1
    for ln in lines:
        t = ln.text
        mb = SOL_B_HEAD_RE.match(t)
        if mb and int(mb.group(1)) == expected:
            cur = ParsedSolution(int(mb.group(1)), "", page=ln.page)
            sols.append(cur)
            expected += 1
            mode = None
            continue
        mc = SOL_C_RE.match(t)
        if mc and int(mc.group(1)) == expected:
            cur = ParsedSolution(int(mc.group(1)), mc.group(2).lower(), page=ln.page)
            sols.append(cur)
            expected += 1
            mode = None
            continue
        ma = SOL_A_RE.match(t)
        if ma and int(ma.group(1)) == expected:
            cur = ParsedSolution(int(ma.group(1)), ma.group(2).lower(), justification=(ma.group(3) or "").strip(), page=ln.page)
            sols.append(cur)
            expected += 1
            mode = "just"
            continue
        if cur is None:
            continue
        mans = SOL_B_ANS_RE.match(t)
        if mans and not cur.letter:
            cur.letter = mans.group(1).lower()
            cur.option_text = mans.group(2).strip()
            mode = "opt"
            continue
        mj = SOL_B_JUST_RE.match(t)
        if mj:
            cur.justification = mj.group(1).strip()
            mode = "just"
            continue
        if mode == "opt":
            cur.option_text = _join(cur.option_text, t)
        elif mode == "just":
            cur.justification = _join(cur.justification, t)
    for s in sols:
        s.justification = s.justification.strip()
        s.option_text = s.option_text.strip()
    # solucionario en cuadrícula compacta («1.B  6.D  11.C…» leído por columnas)
    grid = {}
    for ln in lines:
        mg = SOL_GRID_RE.match(ln.text)
        if mg:
            grid.setdefault(int(mg.group(1)), ParsedSolution(int(mg.group(1)), mg.group(2).lower(), page=ln.page))
    if len(grid) > len(sols) and sorted(grid) == list(range(1, len(grid) + 1)):
        return [grid[n] for n in sorted(grid)]
    # solucionario que repite el test y marca en negrita el texto de la opción correcta
    if not sols:
        bold, num, expected = {}, None, 1
        for ln in lines:
            mq = Q_NUM_RE.match(ln.text)
            if mq and int(mq.group(1)) == expected:
                num, expected = expected, expected + 1
                continue
            mo = OPT_RE.match(ln.text)
            if num and mo and ln.body_bold and num not in bold:
                bold[num] = ParsedSolution(num, mo.group(1).lower(), page=ln.page)
        if sorted(bold) == list(range(1, len(bold) + 1)) and bold:
            return [bold[n] for n in sorted(bold)]
    # solucionario que repite cada enunciado («1. …») seguido de «Respuesta correcta: b) …» y su justificación
    if not sols:
        rep = _parse_repeated_stem_solutions(lines)
        if rep:
            return rep
    return sols


def _parse_repeated_stem_solutions(lines: list[Line]) -> list[ParsedSolution]:
    sols: list[ParsedSolution] = []
    cur: ParsedSolution | None = None
    mode, expected = None, 1
    for ln in lines:
        t = ln.text.strip()
        mq = Q_NUM_RE.match(t)
        if mq and int(mq.group(1)) == expected and (cur is None or cur.letter):
            cur = ParsedSolution(expected, "", page=ln.page)
            sols.append(cur)
            expected += 1
            mode = None
            continue
        if cur is None or t in ("•", "-", "–"):
            continue
        mans = SOL_B_ANS_RE.match(t)
        if mans and not cur.letter:
            cur.letter, cur.option_text, mode = mans.group(1).lower(), mans.group(2).strip(), "opt"
            continue
        mj = SOL_B_JUST_RE.match(t)
        if mj and cur.letter:
            cur.justification, mode = mj.group(1).strip(), "just"
            continue
        if mode == "opt":
            cur.option_text = _join(cur.option_text, t)
        elif mode == "just":
            cur.justification = _join(cur.justification, t)
    sols = [s for s in sols if s.letter]
    for s in sols:
        s.justification, s.option_text = s.justification.strip(), s.option_text.strip()
    return sols if sols and [s.number for s in sols] == list(range(1, len(sols) + 1)) else []


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()
