"""16-17: todas las páginas cargan sin errores y el flujo de examen funciona desde la interfaz."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import exams

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["inicio", "examen", "test", "aleatorio", "fallos", "simulacros", "favoritas", "temario", "resumenes",
         "plan", "estadisticas", "progreso", "historial", "ajustes", "practicas"]


@pytest.mark.parametrize("page", PAGES)
def test_paginas_cargan(page, clean_user):
    # se crea algo de historial para que las páginas muestren datos
    ids = exams.select_questions(["A1-T01"], 5, seed=1)
    eid = exams.create_exam("tema_aleatorio", "practica", "ui", ids, ["A1-T01"])
    a = exams.get_answers(eid)
    exams.answer(eid, 0, a[0]["correct_letter"])
    exams.answer(eid, 1, next(L for L in "abcd" if L != a[1]["correct_letter"]))
    exams.finish(eid)
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["_test_page"] = {"test": "tema"}.get(page, page)
    at.run()
    assert not at.exception, [e.message for e in at.exception]


def test_flujo_examen_practica(clean_user):
    ids = exams.select_questions(["A1-T02"], 3, seed=4)
    eid = exams.create_exam("tema_aleatorio", "practica", "flujo", ids, ["A1-T02"])
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["exam_id"] = eid
    at.session_state["_test_page"] = "examen"
    at.run()
    assert not at.exception
    assert any("PREGUNTA 1 DE 3" in m.value for m in at.markdown)
    # responder la opción correcta pulsando su botón
    correct = exams.get_answers(eid)[0]["correct_letter"]
    at.button(key=f"b_{eid}_0_{'abcd'.index(correct)}").click().run()
    assert not at.exception
    assert exams.get_answers(eid)[0]["selected"] == correct
    assert any("¡Correcto!" in m.value for m in at.markdown)
    # siguiente → fallar → aparece el panel de explicación completo
    nxt = [b for b in at.button if b.label == "Siguiente →"]
    nxt[0].click().run()
    a1 = exams.get_answers(eid)[1]
    wrong = next(L for L in "abcd" if L != a1["correct_letter"])
    at.button(key=f"b_{eid}_1_{'abcd'.index(wrong)}").click().run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    for heading in ["Tu respuesta", "Respuesta correcta", "¿Por qué es incorrecta tu respuesta?", "Recuerda", "Fuente"]:
        assert heading in md, heading
    assert exams.get_answers(eid)[1]["is_correct"] == 0


def test_flujo_examen_finalizar(clean_user):
    ids = exams.select_questions(["A1-T03"], 4, seed=9)
    eid = exams.create_exam("simulacro", "examen", "fin", ids, ["A1-T03"], time_limit_s=3600)
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["exam_id"] = eid
    at.session_state["_test_page"] = "examen"
    at.run()
    at.button(key=f"b_{eid}_0_0").click().run()
    # en modo examen no se muestra la solución
    assert not any("Respuesta correcta" in m.value for m in at.markdown)
    assert exams.get_answers(eid)[0]["selected"] == "a"
    # cambiar de opinión está permitido
    at.button(key=f"b_{eid}_0_1").click().run()
    assert exams.get_answers(eid)[0]["selected"] == "b"
    fin = [b for b in at.button if b.label == "🏁 Finalizar examen"][0]
    fin.click().run()
    conf = [b for b in at.button if b.label == "Finalizar y corregir"]
    assert conf, "debe pedir confirmación antes de finalizar"
    conf[0].click().run()
    assert not at.exception
    assert exams.get_exam(eid)["status"] == "finalizado"
    assert any("Nota" in m.value for m in at.markdown)


def test_practicas_flujo(clean_user):
    from core import bank, db
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["_test_page"] = "practicas"
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert [t.label for t in at.tabs][:4] == ["Práctica 1", "Práctica 2", "Práctica 3", "Práctica 4"]
    assert any("Hacer práctica (25)" in b.label for b in at.button)
    assert any("Hacer práctica (29)" in b.label for b in at.button)
    assert any("no trae solucionario" in w.value for w in at.warning)          # Práctica 4: no se inventan respuestas
    # iniciar la Práctica 1 crea un examen con sus 25 preguntas en orden
    at.button(key="pr1_go").click().run()
    eid = at.session_state["exam_id"]
    e = exams.get_exam(eid)
    assert e["kind"] == "practica" and e["n_questions"] == 25
    t1 = bank.test_by_doc("Benicasim/PRACTICAS/Test - Clase 06-10-2026 (1).pdf")
    assert [a["question_id"] for a in exams.get_answers(eid)] == bank.test_question_ids(t1["id"])
    for a in exams.get_answers(eid)[:3]:
        exams.answer(eid, a["position"], a["correct_letter"])
    exams.finish(eid)
    # el resultado aparece en la práctica y en las estadísticas del apartado
    at2 = AppTest.from_file(APP, default_timeout=90)
    at2.session_state["_test_page"] = "practicas"
    at2.run()
    assert not at2.exception
    assert any("Resultados anteriores" in m.value for m in at2.markdown)
    from core import stats
    row = stats.per_topic().set_index("topic_id").loc["CP"]
    assert row["aciertos"] == 3
    # supuesto (Práctica 2): autocorrección guardada
    at2.segmented_control(key="case2_0_g1").set_value("bien").run()
    at2.segmented_control(key="case2_0_g2").set_value("regular").run()
    at2.button(key="case2_save").click().run()
    h = db.get_setting("practicas_desarrollo")
    assert h and h[-1]["practica"] == 2 and h[-1]["nota"] == 1.5 and h[-1]["bien"] == 1
