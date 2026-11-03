"""Explicaciones de las respuestas.

Tres niveles, siempre distinguidos visualmente en la interfaz:
1. OFICIAL   — letra y justificación del solucionario (texto literal del documento).
2. TEMARIO   — fragmentos literales del temario relacionados (con documento, apartado y página).
3. IA (opcional) — explicación generada por Claude SOLO a partir de los textos anteriores.
   Requiere la variable de entorno ANTHROPIC_API_KEY (o st.secrets) y el paquete `anthropic`.
   Se guarda en caché en la base de datos para no repetir llamadas.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from . import bank, db, srs
from .bank import Question
from .extract.test_parser import LETTERS

AI_MODEL = os.environ.get("OPOS_AI_MODEL", "claude-opus-5-5")


@dataclass
class Explanation:
    question: Question
    selected: str | None
    official_letter: str | None
    official_text: str
    official_justification: str
    solution_source: str
    theory: list[dict] = field(default_factory=list)
    remember: str = ""                 # frase literal extraída de la justificación oficial
    has_specific_wrong_reason: bool = False


def first_sentence(text: str, max_len: int = 220) -> str:
    text = (text or "").strip()
    m = re.match(r"(.+?[.;])(\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= max_len else s[:max_len].rsplit(" ", 1)[0] + "…"


def build(q: Question, selected: str | None) -> Explanation:
    src = ""
    if q.solution_doc_id:
        src = f"{bank.doc_label(q.solution_doc_id)}" + (f", pág. {q.solution_page}" if q.solution_page else "")
    exp = Explanation(
        question=q, selected=selected, official_letter=q.correct_letter, official_text=q.correct_text,
        official_justification=q.justification, solution_source=src, theory=bank.theory_for_question(q.id),
        remember=first_sentence(q.justification))
    # ¿La justificación oficial menciona expresamente la opción elegida?
    if selected and q.justification and selected != q.correct_letter:
        sel_txt = q.options[LETTERS.index(selected)] if LETTERS.index(selected) < len(q.options) else ""
        exp.has_specific_wrong_reason = bool(re.search(rf"\b{selected}\)", q.justification, re.I)) or (
            len(sel_txt) > 15 and sel_txt[:30].lower() in q.justification.lower())
    return exp


# ------------------------------------------------------------------ IA opcional

_KEY_UNSET = object()
_key_cache = _KEY_UNSET
_sdk_ok: bool | None = None


def _api_key() -> str | None:
    """Clave del servidor (variable de entorno o secrets); se lee una sola vez por proceso."""
    global _key_cache
    if _key_cache is _KEY_UNSET:
        k = os.environ.get("ANTHROPIC_API_KEY")
        if not k:
            try:
                import streamlit as st
                k = st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[attr-defined]
            except Exception:
                k = None
        _key_cache = k
    return _key_cache


def _sdk_available() -> bool:
    global _sdk_ok
    if _sdk_ok is None:
        import importlib.util  # comprobar sin importar: el SDK tarda varios segundos en cargarse
        _sdk_ok = importlib.util.find_spec("anthropic") is not None
    return _sdk_ok


def ai_available() -> bool:
    if not db.get_setting("ai_enabled", True):
        return False
    return bool(_api_key()) and _sdk_available()


SYSTEM = (
    "Eres un preparador de oposiciones de Auxiliar Administrativo. Explicas en español claro y breve. "
    "REGLA ESTRICTA: usa únicamente la información de los textos proporcionados (solución oficial, justificación "
    "oficial y fragmentos del temario). No añadas datos, artículos, plazos ni cifras que no aparezcan en ellos. "
    "No cambies la respuesta oficial. Si los textos no bastan para justificar algo, dilo expresamente en el campo "
    "'suficiente' = false y explica qué falta."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "por_que_incorrecta": {"type": "string"},
        "por_que_correcta": {"type": "string"},
        "recuerda": {"type": "string"},
        "suficiente": {"type": "boolean"},
        "limitaciones": {"type": "string"},
    },
    "required": ["por_que_incorrecta", "por_que_correcta", "recuerda", "suficiente", "limitaciones"],
    "additionalProperties": False,
}


def _cache_key(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def ai_explain(exp: Explanation) -> dict | None:
    """Devuelve dict con la explicación generada (o None si no hay IA). Lanza RuntimeError con mensaje legible."""
    q = exp.question
    key = _cache_key("explain-v1", AI_MODEL, q.id, exp.selected or "-")
    cached = db.query_one("SELECT text FROM ai_cache WHERE key=?", (key,))
    if cached:
        return json.loads(cached["text"])
    if not ai_available():
        return None
    import anthropic

    opts = "\n".join(f"{LETTERS[i].upper()}) {o}" for i, o in enumerate(q.options))
    sel = f"{exp.selected.upper()}) {q.options[LETTERS.index(exp.selected)]}" if exp.selected else "(sin responder)"
    frags = "\n\n".join(f"[{bank.doc_label(t['doc_id'])} · {t['section_title']} · pág. {t['page']}]\n{t['text']}"
                        for t in exp.theory)
    prompt = (f"PREGUNTA:\n{q.stem}\n\nOPCIONES:\n{opts}\n\nRESPUESTA DEL ALUMNO: {sel}\n"
              f"SOLUCIÓN OFICIAL: {q.correct_letter.upper()}) {q.correct_text}\n"
              f"JUSTIFICACIÓN OFICIAL (solucionario): {q.justification or '(no consta)'}\n\n"
              f"FRAGMENTOS DEL TEMARIO:\n{frags or '(ninguno)'}\n\n"
              "Devuelve: por_que_incorrecta (por qué la opción del alumno no es correcta; si acertó o no respondió, "
              "explica brevemente por qué las demás no lo son), por_que_correcta (el concepto según los textos), "
              "recuerda (una frase corta fácil de memorizar), suficiente, limitaciones.")
    client = anthropic.Anthropic(api_key=_api_key())
    try:
        resp = client.beta.messages.create(
            model=AI_MODEL,
            max_tokens=4000,
            system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("La clave de API de Anthropic no es válida.")
    except anthropic.RateLimitError:
        raise RuntimeError("Límite de uso de la API alcanzado; inténtalo en unos minutos.")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Error de la API ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise RuntimeError("No hay conexión con la API de Anthropic.")
    if resp.stop_reason == "refusal":
        raise RuntimeError("El modelo no ha generado la explicación.")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Respuesta vacía del modelo.")
    data = json.loads(text)
    db.execute("INSERT OR REPLACE INTO ai_cache(key,text,model,created_at) VALUES (?,?,?,?)",
               (key, json.dumps(data, ensure_ascii=False), resp.model, srs.iso(srs.now())))
    return data


def ai_summary(title: str, passages: list[dict], kind: str) -> str | None:
    """Resumen generado por IA de pasajes literales del temario (opcional, cacheado)."""
    if not passages:
        return None
    body = "\n\n".join(f"[pág. {p['page']}] {p['text']}" for p in passages)[:60000]
    key = _cache_key("summary-v1", AI_MODEL, kind, title, hashlib.sha1(body.encode()).hexdigest())
    cached = db.query_one("SELECT text FROM ai_cache WHERE key=?", (key,))
    if cached:
        return cached["text"]
    if not ai_available():
        return None
    import anthropic
    instr = {
        "completo": "Elabora un resumen estructurado con títulos y viñetas.",
        "rapido": "Elabora una lista de 10-15 ideas clave para repasar justo antes del examen.",
        "esquema": "Elabora un esquema jerárquico con viñetas anidadas (máx. 3 niveles).",
        "errores": "Explica los conceptos de estos apartados en los que el alumno falla, de forma clara y breve.",
    }.get(kind, "Resume el texto.")
    client = anthropic.Anthropic(api_key=_api_key())
    try:
        resp = client.beta.messages.create(
            model=AI_MODEL, max_tokens=8000, system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": f"TEMA: {title}\n\nTEXTO DEL TEMARIO:\n{body}\n\n{instr} "
                                                  "Usa solo este texto, en Markdown, indicando entre paréntesis la página de cada idea."}],
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"No se pudo generar el resumen: {getattr(e, 'message', e)}")
    if resp.stop_reason == "refusal":
        raise RuntimeError("El modelo no ha generado el resumen.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    db.execute("INSERT OR REPLACE INTO ai_cache(key,text,model,created_at) VALUES (?,?,?,?)",
               (key, text, resp.model, srs.iso(srs.now())))
    return text
