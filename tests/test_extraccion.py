"""1-4, 15: extracción, soluciones, duplicados, temas y vínculo con la teoría."""
import json

from core import bank, db, ingest
from core.extract.test_parser import normalize


def test_inventario_basico():
    inv = ingest.build_inventory()
    assert inv["temas_detectados"] == 12
    assert inv["test_originales"] == 12
    assert inv["preguntas_totales"] == 530
    assert inv["preguntas_verificadas"] == 503
    assert inv["preguntas_pendientes"] == 25          # Práctica 1 sin solucionario
    assert inv["preguntas_con_contradiccion"] == 1    # Tema 9 nº 14 (ambigua según el propio solucionario)


def test_numero_preguntas_y_opciones_por_test():
    for t in db.query("SELECT * FROM tests"):
        n = db.scalar("SELECT COUNT(*) FROM question_sources WHERE test_id=?", (t["id"],))
        assert n == t["n_questions"]
        expected = 30 if "Parte 2" in t["doc_id"] else 25 if ("TEMA 9" in t["doc_id"] or "Practica" in t["doc_id"]) else 50
        assert n == expected, t["doc_id"]
    for q in db.query("SELECT options_json, stem FROM questions"):
        opts = json.loads(q["options_json"])
        assert len(opts) == 4 and all(o.strip() for o in opts)
        assert len(q["stem"]) > 10
        assert "pág." not in q["stem"] and "Auxiliar Administrativo Benicàssim" not in q["stem"]


def _q(doc_like: str, number: int):
    r = db.query_one("""SELECT q.* FROM question_sources qs JOIN questions q ON q.id=qs.question_id
                        WHERE qs.doc_id LIKE ? AND qs.number=?""", (f"%{doc_like}%", number))
    return bank.get_question(r["id"])


def test_asociacion_soluciones_formato_letra():
    q = _q("TEMA 1/Test", 7)
    assert q.correct_letter == "a" and q.correct_text.startswith("169 artículos, 4 Disposiciones Adicionales")
    assert "169 artículos" in q.justification
    q = _q("TEMA 1/Test", 1)
    assert q.stem.startswith("¿Cómo define el profesor García de Enterría")
    assert q.correct_letter == "b"
    # Anexo II tema 2 usa letras minúsculas en el solucionario
    q = _q("TEMA 12/Test", 2)
    assert q.correct_letter == "c" and q.status == "verificada"


def test_asociacion_soluciones_formato_largo_tema9():
    q = _q("TEMA 9/Test", 3)
    assert q.correct_letter == "a" and q.correct_text == "Una tasa."
    assert q.justification.startswith("Según el artículo 20.1.a) del TRLRHL")
    q14 = _q("TEMA 9/Test", 14)
    assert q14.status == "contradiccion" and not q14.scoreable
    assert "también válida" in q14.status_reason


def test_pendientes_no_puntuables():
    pend = bank.pending_questions()
    assert len(pend) == 26
    ids = set(bank.question_ids_for_topics(None))
    assert not ids & {q.id for q in pend}


def test_duplicados_e_idempotencia():
    ids_before = {r[0] for r in db.query("SELECT id FROM questions")}
    groups = db.scalar("SELECT COUNT(*) FROM questions WHERE dup_group != id")
    assert groups >= 4  # Temas 3 y 8 comparten preguntas casi idénticas
    ingest.run(verbose=False)  # reimportar no duplica ni cambia identificadores
    ids_after = {r[0] for r in db.query("SELECT id FROM questions")}
    assert ids_before == ids_after
    assert ingest.question_uid("¿Hola?", ["A", "B"]) == ingest.question_uid("  ¿hola? ", ["a", "b"])


def test_clasificacion_por_temas():
    t = {r["id"]: r for r in db.query("SELECT * FROM topics")}
    assert set(t) == {f"A1-T{i:02d}" for i in range(1, 11)} | {"A2-T01", "A2-T02", "CP"}
    assert t["A2-T01"]["folder"].endswith("TEMA 11") and t["A2-T02"]["folder"].endswith("TEMA 12")
    assert len(bank.question_ids_for_topics(["A1-T01"])) == 79
    assert len(bank.question_ids_for_topics(["A1-T09"])) == 24
    assert bank.question_ids_for_topics(["A1-T07"]) == []  # tema sin test
    assert db.scalar("SELECT COUNT(*) FROM esquemas WHERE topic_id='A1-T03'") == 7
    assert db.scalar("SELECT COUNT(*) FROM esquemas WHERE topic_id IS NULL") == 0


def test_vinculo_con_teoria():
    # cada pregunta verificada tiene al menos un fragmento del temario de SU tema
    missing = 0
    for q in db.query("SELECT id, topic_id FROM questions WHERE status='verificada'"):
        links = bank.theory_for_question(q["id"])
        if not links:
            missing += 1
            continue
        assert links[0]["topic_id"] == q["topic_id"]
    assert missing == 0
    # comprobación de contenido: la pregunta del tablón de anuncios apunta al párrafo que lo trata
    r = db.query_one("SELECT id FROM questions WHERE stem LIKE '%tablón de anuncios%'")
    top = bank.theory_for_question(r["id"])[0]
    assert "tablón" in normalize(top["text"]) or "tablon" in normalize(top["text"])
    assert top["page"] >= 2


def test_documentos_originales_intactos(test_db):
    for d in db.query("SELECT id, sha1 FROM documents WHERE kind!='esquema'"):
        from core import config
        from core.extract.pdf_reader import file_hash
        assert file_hash(config.DOCS_DIR / d["id"]) == d["sha1"]
