"""Búsqueda léxica BM25 sobre los párrafos del temario (sin dependencias externas)."""
from __future__ import annotations

import math
import re
from collections import Counter

from .extract.test_parser import normalize

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquellas aquello aquellos aqui asi aun
bajo cada como con contra cual cuales cualquier cuando de del desde donde dos e el ella ellas ello ellos en entre
era eran es esa esas ese eso esos esta estan estas este esto estos fue fueron ha han hasta hay la las le les lo los
mas me mi mientras muy ni no nos o otra otras otro otros para pero poco por porque que quien quienes se sea sean
segun ser si sin sino sobre solo son su sus tal tambien tan tanto te tiene tienen todo todos tras u un una unas uno
unos y ya cuál cuáles qué siguiente siguientes afirmacion correcta incorrecta senale respuesta caso
""".split())


def tokenize(text: str) -> list[str]:
    toks = normalize(text).split()
    out = []
    for t in toks:
        if t in STOPWORDS or (len(t) < 3 and not t.isdigit()):
            continue
        # stemming mínimo para español
        for suf in ("aciones", "iciones", "amente", "mente", "ciones", "cion", "es", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.toks = [tokenize(d) for d in docs]
        self.tf = [Counter(t) for t in self.toks]
        self.len = [len(t) or 1 for t in self.toks]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b
        self.index: dict[str, list[int]] = {}
        for i, t in enumerate(self.tf):
            for w in t:
                self.index.setdefault(w, []).append(i)

    def scores(self, query: str, allowed: set[int] | None = None) -> dict[int, float]:
        q = Counter(tokenize(query))
        res: dict[int, float] = {}
        for w, qf in q.items():
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i in self.index[w]:
                if allowed is not None and i not in allowed:
                    continue
                f = self.tf[i][w]
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                res[i] = res.get(i, 0.0) + idf * f * (self.k1 + 1) / denom
        return res

    def top(self, query: str, k: int = 3, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        s = self.scores(query, allowed)
        return sorted(s.items(), key=lambda x: -x[1])[:k]


_ART_RE = re.compile(r"art(?:[íi]culo|s?\.)\s*(\d+)", re.I)


def article_refs(text: str) -> set[str]:
    return set(_ART_RE.findall(text or ""))
