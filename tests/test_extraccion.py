"""1-4, 15: extracción, soluciones, duplicados, temas y vínculo con la teoría."""
import json

from core import bank, db, ingest
from core.extract.test_parser import normalize


def test_inventario_basico():
    inv = ingest.build_inventory()
    assert inv["temas_detectados"] == 12
    assert inv["test_originales"] == 15               # Temas 7 y 10 en un único test · Prácticas 1, 3 y 4
    assert inv["preguntas_totales"] == 670
    assert inv["preguntas_verificadas"] == 627
    assert inv["preguntas_pendientes"] == 41          # Práctica 4 sin solucionario (40) + Práctica 3 nº 30
    assert inv["preguntas_con_contradiccion"] == 1    # Tema 9 nº 14 (ambigua según el propio solucionario)


def test_numero_preguntas_y_opciones_por_test():
    for t in db.query("SELECT * FROM tests"):
        n = db.scalar("SELECT COUNT(*) FROM question_sources WHERE test_id=?", (t["id"],))
        assert n == t["n_questions"]
        expected = {"T:Test Tema 7 y 10": 70}.get(t["id"]) or (
            30 if ("Parte 2" in t["doc_id"] or "20-10" in t["doc_id"]) else 40 if "27-10" in t["doc_id"]
            else 25 if ("TEMA 9" in t["doc_id"] or "06-10" in t["doc_id"]) else 50)
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
    assert len(pend) == 42
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
    assert len(bank.question_ids_for_topics(["A1-T07"])) == 45  # 20 antiguas + 25 del test nuevo
    assert len(bank.question_ids_for_topics(["A1-T10"])) == 25  # LPRL del test nuevo
    assert db.scalar("SELECT COUNT(*) FROM esquemas WHERE topic_id='A1-T03'") == 7
    assert db.scalar("SELECT COUNT(*) FROM esquemas WHERE topic_id IS NULL") == 0


def test_vinculo_con_teoria():
    # cada pregunta verificada tiene al menos un fragmento del temario de SU tema
    missing = 0
    for q in db.query("SELECT id, topic_id FROM questions WHERE status='verificada' AND topic_id != 'CP'"):  # prácticas: todo el temario
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


def test_test_tema_7_y_10_unificado():
    t = db.query_one("SELECT * FROM tests WHERE id='T:Test Tema 7 y 10'")
    assert t["name"] == "Test Tema 7 y 10" and t["n_questions"] == t["n_verified"] == 70
    assert not db.query("SELECT 1 FROM tests WHERE doc_id LIKE '%TEMA 7/Test Tema 7%' AND id != 'T:Test Tema 7 y 10'")
    ids = bank.test_question_ids(t["id"])
    assert len(ids) == len(set(ids)) == 70
    assert len({bank.get_question(i).dup_group for i in ids}) == 70  # sin repetidas
    # aparece en Tema 7 y en Tema 10
    assert t["id"] in [x["id"] for x in bank.tests_for_topic("A1-T07")]
    assert t["id"] in [x["id"] for x in bank.tests_for_topic("A1-T10")]


def test_correcciones_por_enunciado():
    for frag in ("conforme al artículo 62 del TREBEP", "excedencia por cuidado de familiares del artículo 89.4"):
        r = db.query("SELECT * FROM questions WHERE stem LIKE ?", (f"%{frag}%",))
        assert len(r) == 1 and r[0]["correct_letter"] == "c" and r[0]["status"] == "verificada"


def test_practicas():
    t1 = bank.test_by_doc("Benicasim/PRACTICAS/Test - Clase 06-10-2026 (1).pdf")
    t3 = bank.test_by_doc("Benicasim/PRACTICAS/Test - Clase 20-10-2026  (1).pdf")
    t4 = bank.test_by_doc("Benicasim/PRACTICAS/Test - Clase 27-10-2026.pdf")
    assert len(bank.test_question_ids(t1["id"])) == 25
    assert len(bank.test_question_ids(t3["id"])) == 29        # el solucionario no trae la nº 30
    assert bank.test_question_ids(t4["id"]) == []              # sin solucionario: no se inventan respuestas
    assert t1["topic_id"] == t3["topic_id"] == t4["topic_id"] == "CP"
    # Caso practico/ contiene copias idénticas: no se duplican
    assert not db.query("SELECT 1 FROM documents WHERE id LIKE 'Caso practico/%'")
    q = _q("06-10-2026", 1)
    assert q.correct_letter == "b" and q.justification.startswith("El artículo 53.1.a)")
