"""Divide un documento de teoría en apartados (encabezados) y párrafos con su página."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import groupby

from .pdf_reader import Line
from .test_parser import _join

NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\s*[.\-–]*\s*-?\s*\S")
ROMAN_RE = re.compile(r"^([IVX]+)\s*[.\-–]+\s*\S")
LETTER_RE = re.compile(r"^[A-H]\)\s+\S")
ARTICLE_RE = re.compile(r"^Art[íi]culo\s+\d+", re.I)


@dataclass
class Paragraph:
    text: str
    page: int


@dataclass
class Section:
    title: str
    level: int
    page: int
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)


def _heading_level(title: str) -> int | None:
    m = NUM_RE.match(title)
    if m and len(title) < 200:
        return min(m.group(1).count(".") + 1 if not m.group(1).endswith(".") else m.group(1).count("."), 4) or 1
    if ROMAN_RE.match(title):
        return 1
    if LETTER_RE.match(title) or ARTICLE_RE.match(title):
        return 3
    return None


def parse_theory(lines: list[Line], skip_cover: bool = True) -> list[Section]:
    body = [l for l in lines if not (skip_cover and l.page == 1)]
    sections: list[Section] = [Section("Introducción", 1, body[0].page if body else 1)]
    for _, grp in groupby(body, key=lambda l: l.block):
        blk = list(grp)
        text = ""
        for l in blk:
            text = _join(text, l.text)
        text = text.strip()
        if not text:
            continue
        all_bold = all(l.bold for l in blk)
        lvl = _heading_level(text)
        is_heading = all_bold and len(text) < 220 and (
            lvl is not None or text.isupper() or (len(text) < 110 and not text.endswith((",", ";")))
        )
        if is_heading:
            level = lvl if lvl is not None else (2 if text.isupper() else 3)
            # títulos de varias líneas partidos en bloques consecutivos
            last = sections[-1]
            if not last.paragraphs and last.title != "Introducción" and last.page == blk[0].page and len(last.title) < 120 \
                    and _heading_level(text) is None and not last.title.endswith("."):
                last.title = _join(last.title, text)
                continue
            sections.append(Section(text, level, blk[0].page))
        else:
            sections[-1].paragraphs.append(Paragraph(text, blk[0].page))
    intro = sections[0]
    if not intro.paragraphs:
        sections = sections[1:]  # marcador sin contenido: el documento empieza directamente con un apartado
    return [s for s in sections if s.paragraphs or s.level <= 2]
