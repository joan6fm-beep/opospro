"""5-14: test aleatorios, originales, puntuación, guardado, historial, favoritos, repaso, estadísticas y recuperación."""
from datetime import datetime, timedelta

import pytest

from core import bank, db, exams, plan, srs, stats, summaries, userdata


def test_aleatorio_sin_repetidas(clean_user):
    for seed in range(40):
        ids = exams.select_questions(None, 100, exams.SEL_ALL, seed=seed)
        assert len(ids) == 100 and len(set(ids)) == 100
        groups = [bank.get_question(i).dup_group for i in ids]
        assert len(groups) == len(set(groups)), "dos preguntas casi idénticas en el mismo examen"


def test_aleatorio_respeta_temas_y_maximo(clean_user):
    ids = exams.select_questions(["A1-T09"], 50, exams.SEL_ALL)
    assert len(ids) == 24  # el tema solo tiene 24 puntuables
    allowed = set(bank.question_ids_for_topics(["A1-T09"]))
    assert set(ids) <= allowed
    ids = exams.select_questions(["A1-T01", "A2-T02"], 30)
    assert set(ids) <= set(bank.question_ids_for_topics(["A1-T01", "A2-T02"]))


def test_tests_distintos_entre_si(clean_user):
    first = exams.select_questions(["A1-T01"], 20, seed=1)
    eid = exams.create_exam("tema_aleatorio", "examen", "t", first, ["A1-T01"])
    for i, a in enumerate(exams.get_answers(eid)):
        exams.answer(eid, i, a["correct_letter"])
    exams.finish(eid)
    second = exams.select_questions(["A1-T01"], 20, seed=2)
    assert len(set(first) & set(second)) <= 5  # se priorizan las no vistas


def test_test_original_orden(clean_user):
    t = db.query_one("SELECT * FROM tests WHERE doc_id LIKE '%TEMA 2/Test%'")
    qids = bank.test_question_ids(t["id"])
    eid = exams.create_exam("tema_original", "examen", t["name"], qids, [t["topic_id"]])
    ans = exams.get_answers(eid)
    nums = [db.scalar("SELECT number FROM question_sources WHERE test_id=? AND question_id=?", (t["id"], a["question_id"])) for a in ans]
    assert nums == list(range(1, 51))
    t9 = db.query_one("SELECT * FROM tests WHERE doc_id LIKE '%TEMA 9/Test%'")
    assert len(bank.test_question_ids(t9["id"])) == 24  # excluye la pregunta ambigua


def test_puntuacion():
    ans = [{"selected": "a", "is_correct": 1}] * 6 + [{"selected": "b", "is_correct": 0}] * 3 + [{"selected": None, "is_correct": None}]
    r = exams.compute_result(ans, {"correct": 1, "wrong": 1 / 3, "blank": 0, "scale": 10})
    assert (r.correct, r.wrong, r.blank) == (6, 3, 1)
    assert r.score == pytest.approx(5.0) and r.grade == pytest.approx(5.0) and r.pct == 60.0
    r = exams.compute_result([{"selected": "b", "is_correct": 0}] * 4, {"correct": 1, "wrong": 1, "blank": 0, "scale": 10})
    assert r.grade == 0.0  # la nota nunca es negativa


def test_guardado_y_modo_practica(clean_user):
    ids = exams.select_questions(["A1-T04"], 5, seed=3)
    eid = exams.create_exam("tema_aleatorio", "practica", "p", ids, ["A1-T04"])
    a0 = exams.get_answers(eid)[0]
    wrong = next(L for L in "abcd" if L != a0["correct_letter"])
    assert exams.answer(eid, 0, wrong) is False
    # en práctica la respuesta queda fijada
    assert exams.answer(eid, 0, a0["correct_letter"]) is False
    assert exams.get_answers(eid)[0]["selected"] == wrong
    st = db.query_one("SELECT * FROM review_state WHERE question_id=?", (a0["question_id"],))
    assert st["n_wrong"] == 1 and st["box"] == 0


def test_historial_inmutable(clean_user):
    qid = bank.question_ids_for_topics(["A1-T05"])[0]
    q = bank.get_question(qid)
    eid = exams.create_exam("tema_aleatorio", "examen", "h", [qid])
    exams.answer(eid, 0, q.correct_letter)
    res1 = exams.finish(eid)
    # se responde de nuevo mal en otro examen y se altera el banco: el historial no cambia
    e2 = exams.create_exam("tema_aleatorio", "examen", "h2", [qid])
    exams.answer(e2, 0, next(L for L in "abcd" if L != q.correct_letter))
    exams.finish(e2)
    db.execute("UPDATE questions SET stem='MODIFICADA' WHERE id=?", (qid,))
    a = exams.get_answers(eid)[0]
    assert a["stem"] == q.stem and a["is_correct"] == 1
    assert exams.get_exam(eid)["n_correct"] == res1.correct == 1
    db.execute("UPDATE questions SET stem=? WHERE id=?", (q.stem, qid))
    assert len(exams.history()) == 2


def test_favoritos_y_notas(clean_user):
    qid = bank.question_ids_for_topics(["A1-T06"])[0]
    assert userdata.toggle_favorite(qid) is True and userdata.is_favorite(qid)
    assert userdata.favorite_ids("A1-T06") == [qid] and userdata.favorite_ids("A1-T01") == []
    userdata.save_note(qid, "Ojo con el plazo")
    assert userdata.get_note(qid) == "Ojo con el plazo"
    assert userdata.toggle_favorite(qid) is False and not userdata.is_favorite(qid)
    userdata.save_note(qid, "")
    assert userdata.get_note(qid) == ""


def test_repeticion_espaciada(clean_user):
    qid = bank.question_ids_for_topics(["A1-T08"])[0]
    p = srs.params()
    t0 = datetime(2026, 1, 1, 10, 0)
    srs.record(qid, False, when=t0)
    s = dict(db.query_one("SELECT * FROM review_state WHERE question_id=?", (qid,)))
    assert s["box"] == 0 and s["due_at"] == t0.isoformat() and srs.state_label(s) == "Fallada"
    assert qid in srs.due_ids()
    for k in range(1, p["mastery_box"] + 1):
        srs.record(qid, True, when=t0 + timedelta(days=k))
    s = dict(db.query_one("SELECT * FROM review_state WHERE question_id=?", (qid,)))
    assert s["box"] == p["mastery_box"] and srs.state_label(s) == "Recuperada"
    assert qid not in srs.due_ids() or s["due_at"] <= srs.iso(srs.now())
    srs.record(qid, False)
    s = dict(db.query_one("SELECT * FROM review_state WHERE question_id=?", (qid,)))
    assert s["box"] == 0 and s["n_wrong"] == 2 and s["correct_after_wrong"] == 0
    # acierto a la primera → caja inicial configurada
    q2 = bank.question_ids_for_topics(["A1-T08"])[1]
    srs.record(q2, True)
    assert db.scalar("SELECT box FROM review_state WHERE question_id=?", (q2,)) == p["first_correct_box"]


def test_seleccion_falladas_y_dificiles(clean_user):
    ids = bank.question_ids_for_topics(["A1-T02"])[:6]
    for i in ids[:3]:
        srs.record(i, False)
    for i in ids[3:]:
        srs.record(i, True)
    assert set(exams.select_questions(["A1-T02"], None, exams.SEL_FAILED)) == set(ids[:3])
    assert set(exams.select_questions(["A1-T02"], None, exams.SEL_CORRECT)) == set(ids[3:])
    hard = exams.select_questions(["A1-T02"], 3, exams.SEL_HARD)
    assert set(hard) == set(ids[:3])
    new = exams.select_questions(["A1-T02"], None, exams.SEL_NEW)
    assert not set(new) & set(ids) and len(new) == 44
    smart = exams.select_questions(["A1-T02"], 10, exams.SEL_SMART)
    assert len(smart) == len(set(smart)) == 10 and set(ids[:3]) <= set(smart)


def test_estadisticas_y_plan(clean_user):
    ids = exams.select_questions(["A1-T01"], 10, seed=5)
    eid = exams.create_exam("tema_aleatorio", "examen", "s", ids, ["A1-T01"])
    ans = exams.get_answers(eid)
    for i, a in enumerate(ans[:7]):
        exams.answer(eid, i, a["correct_letter"])
    for i, a in enumerate(ans[7:9], start=7):
        exams.answer(eid, i, next(L for L in "abcd" if L != a["correct_letter"]))
    exams.add_elapsed(eid, 600)
    exams.finish(eid)
    ov = stats.overview()
    assert (ov["exams"], ov["answered"], ov["correct"], ov["wrong"], ov["blank"]) == (1, 9, 7, 2, 1)
    assert ov["pct"] == pytest.approx(7 / 9 * 100) and ov["seconds"] == 600
    pt = stats.per_topic().set_index("topic_id")
    assert pt.loc["A1-T01", "respuestas"] == 9 and pt.loc["A1-T01", "fallos"] == 2
    assert len(stats.failed_questions_df()) == 2
    pr = plan.topic_priorities()
    assert pr.iloc[0]["topic_id"] != "A1-T01"  # el tema practicado con 78 % no es el más prioritario
    recs = plan.recommendations()
    assert any(r.action == "fallos" for r in recs)
    pats = summaries.error_patterns(min_fails=1)
    assert sum(len(p["questions"]) for p in pats) == 2


def test_recuperacion_examen_interrumpido(clean_user):
    ids = exams.select_questions(["A2-T01"], 10, seed=7)
    eid = exams.create_exam("simulacro", "examen", "sim", ids, ["A2-T01"], time_limit_s=600)
    exams.answer(eid, 0, "a")
    exams.answer(eid, 3, "c")
    exams.set_flag(eid, 3, True)
    exams.set_position(eid, 4)
    exams.add_elapsed(eid, 95)
    # "se cierra la aplicación": todo está en la base de datos, nada en memoria
    opens = exams.open_exams()
    assert [e["id"] for e in opens] == [eid]
    e = exams.get_exam(eid)
    a = exams.get_answers(eid)
    assert e["current_index"] == 4 and e["elapsed_s"] == 95 and e["time_limit_s"] == 600
    assert a[0]["selected"] == "a" and a[3]["selected"] == "c" and a[3]["flagged"] == 1
    exams.abandon(eid)
    assert exams.open_exams() == []


def test_resumenes_extractivos_son_literales():
    from core import db as _db
    for tid in ["A1-T01", "A1-T05", "A1-T09"]:
        sents = summaries.quick_summary(tid, 15)
        assert len(sents) >= 10
        for s in sents:
            texts = " ".join(r["text"] for r in _db.query("SELECT text FROM chunks WHERE section_id=?", (s.section_id,)))
            assert s.text in texts  # cita literal del temario


def test_copia_y_exportacion(clean_user):
    userdata.toggle_favorite(bank.question_ids_for_topics(["A1-T03"])[0])
    p = userdata.backup("test")
    assert p.exists()
    raw = userdata.export_progress_json()
    db.execute("DELETE FROM favorites")
    userdata.import_progress_json(raw)
    assert len(userdata.favorite_ids()) == 1
    assert userdata.export_zip()[:2] == b"PK"
    p.unlink()


def test_simulacro_tema1_incluye_parte2(clean_user):
    """Al elegir el Tema 1 en un simulacro entran preguntas de sus dos test (Parte 1 y Parte 2)."""
    parts = [t for t in bank.tests_for_topic("A1-T01")]
    assert len(parts) == 2 and any("Parte 2" in t["name"] for t in parts)
    p2 = next(t for t in parts if "Parte 2" in t["name"])
    p2_ids = set(bank.test_question_ids(p2["id"]))
    pool = set(bank.question_ids_for_topics(["A1-T01"]))
    assert p2_ids and p2_ids <= pool
    seen = set()
    for seed in range(5):
        seen |= set(exams.select_questions(["A1-T01"], 50, exams.SEL_ALL, seed=seed))
    assert seen & p2_ids
    eid = exams.create_exam("simulacro", "examen", "S", exams.select_questions(None, 50), None,
                            exams.Scoring(1, 1 / 3, 0, 10), 3600)
    ans = exams.get_answers(eid)
    assert len(ans) == 50
    for a in ans[:30]:
        exams.answer(eid, a["position"], a["correct_letter"])
    res = exams.finish(eid)
    assert res.correct == 30 and res.blank == 20 and res.grade == 6.0
    assert exams.history(kind="simulacro")[0]["id"] == eid
