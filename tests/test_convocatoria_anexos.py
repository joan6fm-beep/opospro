"""Examen de primera convocatoria, simulacros por anexos y temas 1-6 del Anexo II."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from core import bank, db, exams, summaries

APP = str(Path(__file__).resolve().parent.parent / "app.py")
# respuestas de EXAMEN/Solucionario.png (preguntas 1-30)
SOLUCIONARIO = "bcdbcdbcdbcccacdbdaabbbbdcbdcb"


def test_examen_convocatoria_30_preguntas_y_solucionario():
    t = bank.exam_tests()
    assert [x["name"] for x in t] == ["Examen primera convocatoria"]
    ids = bank.test_question_ids(t[0]["id"], scoreable_only=False)
    assert len(ids) == 30 == len(set(ids)) == len(bank.test_question_ids(t[0]["id"]))
    qs = bank.get_questions(ids)
    assert [qs[i].source_number for i in ids] == list(range(1, 31))
    assert "".join(qs[i].correct_letter for i in ids) == SOLUCIONARIO
    assert all(qs[i].topic_id == "EX1" and len(qs[i].options) == 4 for i in ids)
    # no se mezclan con otros test ni con los temas del temario
    others = db.scalar("SELECT COUNT(*) FROM question_sources WHERE question_id IN (%s) AND test_id!=?"
                       % ",".join("?" * 30), (*ids, t[0]["id"]))
    assert others == 0
    assert not set(ids) & set(bank.question_ids_for_topics([x["id"] for x in bank.topics_by_anexo("todos")]))


def test_examen_convocatoria_se_corrige_y_guarda(clean_user):
    t = bank.exam_tests()[0]
    ids = bank.test_question_ids(t["id"])
    eid = exams.create_exam("convocatoria", "examen", t["name"], ids, ["EX1"], extra={"test_id": t["id"]})
    for a in exams.get_answers(eid)[:20]:
        exams.answer(eid, a["position"], a["correct_letter"])
    a = exams.get_answers(eid)[20]
    exams.answer(eid, 20, next(L for L in "abcd" if L != a["correct_letter"]))
    r = exams.finish(eid)
    assert (r.n, r.correct, r.wrong, r.blank) == (30, 20, 1, 9)
    h = exams.history(kind="convocatoria")
    assert h and h[0]["n_correct"] == 20
    from core import stats
    assert stats.per_topic().set_index("topic_id").loc["EX1"]["aciertos"] == 20


def test_anexos_y_etiquetas():
    a1 = [t["id"] for t in bank.topics_by_anexo("I", include_empty=True)]
    a2 = [t["id"] for t in bank.topics_by_anexo("II", include_empty=True)]
    assert a1 == [f"A1-T{n:02d}" for n in range(1, 11)]
    assert a2 == [f"A2-T{n:02d}" for n in range(1, 7)]
    assert len(bank.topics_by_anexo("todos", include_empty=True)) == 16
    assert bank.topic_label("A2-T01", short=True) == "Anexo II · Tema 1"
    assert bank.topic_label("A2-T06", short=True) == "Anexo II · Tema 6"
    assert bank.topic_label("A1-T01", short=True) == "Anexo I · Tema 1"
    # los temas 11-16 del proyecto son los temas 1-6 del Anexo II
    for n in range(1, 7):
        assert bank.topic(f"A2-T{n:02d}")["folder"] == f"Benicasim/TEMA {10 + n}"
        assert bank.topic(f"A2-T{n:02d}")["n_sections"] > 0


def test_simulacro_por_anexo_sin_mezclas_ni_duplicadas():
    for anexo, prefix in (("I", "A1-"), ("II", "A2-")):
        tps = [t["id"] for t in bank.topics_by_anexo(anexo)]
        ids = exams.select_questions(tps, 500, seed=3)
        assert ids and len(ids) == len(set(ids))
        assert all(q.topic_id.startswith(prefix) for q in bank.get_questions(ids).values())
    todos = exams.select_questions([t["id"] for t in bank.topics_by_anexo("todos")], 2000, seed=1)
    tops = {q.topic_id[:3] for q in bank.get_questions(todos).values()}
    assert tops == {"A1-", "A2-"} and len(todos) == len(set(todos))
    # tema concreto: solo sus preguntas
    one = exams.select_questions(["A2-T02"], 20, seed=2)
    assert {q.topic_id for q in bank.get_questions(one).values()} == {"A2-T02"}


def test_tema1_incluye_parte2():
    parte2 = next(t for t in db.query("SELECT * FROM tests") if "Parte 2" in t["doc_id"])
    p2 = set(bank.test_question_ids(parte2["id"]))
    # 30 preguntas, una idéntica a otra de la Parte 1
    assert len(p2) >= 29 and p2 <= set(bank.question_ids_for_topics(["A1-T01"]))


def test_resumenes_estudio_anexo2():
    for n in range(1, 7):
        md = summaries.study_summary(f"A2-T{n:02d}")
        assert md and md.startswith(f"# Anexo II · Tema {n}") and "Esquema" in md


def test_paginas_simulacros_y_convocatoria(clean_user):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["_test_page"] = "simulacros"
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    at.segmented_control(key="sim_anexo").set_value("II").run()
    ms = at.multiselect(key="sim_topics_II_anexo2")
    assert ms.options and all(o.startswith("Anexo II · Tema") for o in ms.options)
    ms.set_value(["A2-T01"]).run()
    assert not at.exception
    sub = [b for b in at.button if "Empezar simulacro" in b.label]
    sub[0].click().run()
    assert not at.exception
    e = exams.get_exam(at.session_state["exam_id"])
    assert e["kind"] == "simulacro"
    assert {a["topic_id"] for a in exams.get_answers(e["id"])} == {"A2-T01"}
    at2 = AppTest.from_file(APP, default_timeout=90)
    at2.session_state["_test_page"] = "convocatoria"
    at2.run()
    assert not at2.exception, [e.message for e in at2.exception]
    assert any("Hacer el examen completo (30)" in b.label for b in at2.button)
    at2.button(key="cv_EX1_go").click().run()
    e2 = exams.get_exam(at2.session_state["exam_id"])
    assert e2["kind"] == "convocatoria" and e2["n_questions"] == 30
    at3 = AppTest.from_file(APP, default_timeout=90)
    at3.session_state["_test_page"] = "resumenes"
    at3.session_state["res_sel"] = "A2-T03"
    at3.run()
    assert not at3.exception
    assert any("Anexo II · Tema 3" in m.value for m in at3.markdown)


def test_fuentes_anexo1():
    src = bank.anexo1_sources()
    kinds = [x["kind"] for x in src]
    assert kinds.count("practica") == 6 and kinds.count("final") == 1 and kinds.count("convocatoria") == 1
    final = next(x for x in src if x["kind"] == "final")
    conv = next(x for x in src if x["kind"] == "convocatoria")
    assert final["n"] == 49 and conv["n"] == 30
    # una fuente concreta: exactamente sus preguntas oficiales
    assert set(exams.select_questions([], None, test_ids=[conv["id"]])) == set(bank.test_question_ids(conv["id"]))
    # varias prácticas + temas: sin repetidas ni preguntas sin solución oficial
    allsrc = [x["id"] for x in src]
    a1 = [t["id"] for t in bank.topics_by_anexo("I")]
    ids = exams.select_questions(a1, None, test_ids=allsrc)
    assert len(ids) == len(set(ids))
    qs = bank.get_questions(ids)
    assert all(q.scoreable for q in qs.values())
    assert {q.topic_id for q in qs.values()} <= set(a1) | {"CP", "EX1"}
    assert not any(q.topic_id.startswith("A2-") for q in qs.values())
    assert set(bank.test_question_ids(final["id"])) - set(ids) <= {i for i in bank.test_question_ids(final["id"])
                                                                    if qs.get(i) is None}


def test_simulacro_ui_anexo1_fuentes(clean_user):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["_test_page"] = "simulacros"
    at.run()
    at.segmented_control(key="sim_anexo").set_value("I").run()
    at.selectbox(key="sim_pre_I").set_value("final").run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.multiselect(key="sim_topics_I_final").value == []
    [b for b in at.button if "Empezar simulacro" in b.label][0].click().run()
    e = exams.get_exam(at.session_state["exam_id"])
    final = next(x for x in bank.anexo1_sources() if x["kind"] == "final")
    got = {a["question_id"] for a in exams.get_answers(e["id"])}
    assert got <= set(bank.test_question_ids(final["id"])) and len(got) == min(49, e["n_questions"])
