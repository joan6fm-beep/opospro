"""Lectura mínima de documentos Word (.docx) sin dependencias externas.

Word no guarda páginas: se usan los saltos de página explícitos cuando existen.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .pdf_reader import Line, clean_text

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx_lines(path: Path) -> list[Line]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    out: list[Line] = []
    page, bid = 1, 0
    for p in root.iter(W + "p"):
        bid += 1
        texts, bolds = [], []
        for r in p.iter(W + "r"):
            if r.find(f"{W}br[@{W}type='page']") is not None or r.find(W + "lastRenderedPageBreak") is not None:
                page += 1
            t = "".join(x.text or "" for x in r.iter(W + "t"))
            if t.strip():
                texts.append(t)
                rpr = r.find(W + "rPr")
                bolds.append(rpr is not None and rpr.find(W + "b") is not None)
        text = clean_text("".join(texts))
        if text:
            out.append(Line(text, page, 12.0, bool(bolds) and all(bolds), bid))
    return out


def docx_pages(path: Path) -> int:
    lines = read_docx_lines(path)
    return max((l.page for l in lines), default=1)


def docx_title(path: Path) -> tuple[str, str]:
    lines = read_docx_lines(path)[:15]
    full = "\n".join(l.text for l in lines)
    m = next((l.text for l in lines if re.match(r"tema\s*\d+", l.text, re.I)), lines[0].text if lines else "")
    return m, full
