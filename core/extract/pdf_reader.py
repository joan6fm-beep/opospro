"""Lectura de PDF línea a línea conservando página y formato (negrita/tamaño)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

HEADER_RE = re.compile(r"^p[áa]g\.\s*\d+\s*$", re.I)
NOISE_RE = re.compile(r"^\[Escriba aquí\]$", re.I)

OPT_LABEL_RE = re.compile(r"^[a-hA-H]\)$")

@dataclass
class Line:
    text: str
    page: int          # página física del PDF (1-based)
    size: float
    bold: bool
    block: int = 0     # índice global de bloque (párrafo) en el documento
    body_bold: bool = False  # texto en negrita tras la etiqueta «a)» (solucionarios que marcan la opción correcta así)


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(t: str) -> str:
    t = t.replace(" ", " ").replace("``", "").replace("­", "")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def read_lines(path: Path, strip_headers: bool = True) -> list[Line]:
    """Devuelve las líneas del documento eliminando las cabeceras repetidas de página.

    Las cabeceras de estos documentos son: «<título>», «Auxiliar Administrativo Benicàssim», «pág. N».
    Se elimina todo lo que aparece en la página antes de la línea «pág. N» (si está en las 5 primeras).
    """
    doc = pymupdf.open(path)
    out: list[Line] = []
    bid = 0
    for pno, page in enumerate(doc, start=1):
        plines: list[Line] = []
        for block in page.get_text("dict")["blocks"]:
            bid += 1
            for l in block.get("lines", []):
                spans = [s for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = clean_text("".join(s["text"] for s in l["spans"]))
                if not text or NOISE_RE.match(text):
                    continue
                bold = all(("Bold" in s["font"]) or (s["flags"] & 16) for s in spans)
                size = max(s["size"] for s in spans)
                body = [s for s in spans if not OPT_LABEL_RE.match(s["text"].strip())]
                body_bold = bool(body) and len(body) < len(spans) and all(("Bold" in s["font"]) or (s["flags"] & 16) for s in body)
                plines.append(Line(text, pno, round(size, 1), bool(bold), bid, body_bold))
        if strip_headers:
            for i, ln in enumerate(plines[:6]):
                if HEADER_RE.match(ln.text):
                    plines = plines[i + 1:]
                    break
        out.extend(plines)
    return out


def page_count(path: Path) -> int:
    return len(pymupdf.open(path))


def title_page_info(path: Path) -> tuple[str, str]:
    """(texto con la fuente más grande de la portada, texto completo de la portada)."""
    doc = pymupdf.open(path)
    page = doc[0]
    best, best_size = "", 0.0
    for block in page.get_text("dict")["blocks"]:
        for l in block.get("lines", []):
            for s in l["spans"]:
                if s["text"].strip() and s["size"] > best_size:
                    best, best_size = s["text"].strip(), s["size"]
    return best, page.get_text()


def render_page_png(path: Path, page: int, zoom: float = 1.6) -> bytes:
    doc = pymupdf.open(path)
    pix = doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")
