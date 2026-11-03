"""Banco de preguntas, inventario, incidencias, repaso, IA, copias de seguridad e importación."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import bank, cloudsync, config, db, explain, ingest, srs, userdata
from core.extract.test_parser import LETTERS
from ui import nav
from ui.components import badge, esc, kpi_row


def _inventory() -> None:
    inv = json.loads(config.INVENTORY_JSON.read_text(encoding="utf-8")) if config.INVENTORY_JSON.exists() else ingest.build_inventory()
    kpi_row([("Temas", str(inv["temas_detectados"]), ""), ("Documentos", str(inv["documentos"]), ""),
             ("Test originales", str(inv["test_originales"]), ""), ("Preguntas", str(inv["preguntas_totales"]), f"{inv['preguntas_unicas']} únicas")])
    st.write("")
    kpi_row([("Verificadas", str(inv["preguntas_verificadas"]), "usables en test"),
             ("Pendientes", str(inv["preguntas_pendientes"]), "sin solución verificable"),
             ("Contradicciones", str(inv["preguntas_con_contradiccion"]), "excluidas"),
             ("Apartados teoría", str(inv["apartados_teoria"]), f"{inv['esquemas']} esquemas")])
    st.caption(f"Inventario generado {inv['generado'].replace('T', ' ')} · también en `data/INVENTARIO.md` y `data/inventario.json`.")
    st.dataframe(pd.DataFrame(inv["por_tema"]), hide_index=True, column_config={
        "tema": "ID", "nombre": "Tema", "preguntas": "Preguntas", "verificadas": "Verificadas",
        "apartados_teoria": "Apartados", "esquemas": "Esquemas"})
    with st.expander("Test originales y su solucionario"):
        st.dataframe(pd.DataFrame(inv["test"])[["doc_id", "topic_id", "n_questions", "n_verified", "solution_doc_id"]],
                     hide_index=True)
    with st.expander(f"Incidencias de la extracción ({len(inv['incidencias'])})"):
        df = pd.DataFrame(inv["incidencias"])
        if not df.empty:
            st.dataframe(df[["kind", "doc_id", "detail"]], hide_index=True)
    with st.expander("Todos los documentos"):
        st.dataframe(pd.DataFrame(inv["documentos_detalle"]), hide_index=True)


def _pending() -> None:
    st.markdown("Estas preguntas **no se usan en test puntuables** porque no tienen una solución verificable en los documentos "
                "o el solucionario es contradictorio/ambiguo.")
    for q in bank.pending_questions():
        tag = badge("pend", "Contradicción" if q.status == "contradiccion" else "Pendiente")
        with st.expander(f"{bank.doc_label(q.source_doc_id)} · nº {q.source_number} — {q.stem[:100]}"):
            st.markdown(f"{tag} {esc(q.status_reason)}", unsafe_allow_html=True)
            st.markdown(f"**{esc(q.stem)}**")
            for i, o in enumerate(q.options):
                st.markdown(f"{LETTERS[i].upper()}) {esc(o)}")
            if q.justification:
                st.markdown(f'{badge("oficial", "Texto del solucionario")} {esc(q.justification)}', unsafe_allow_html=True)
            if q.status == "pendiente":
                st.markdown("---")
                st.caption("Si has verificado la respuesta en una fuente oficial (corrección del profesor, solucionario nuevo…) "
                           "puedes introducirla. Quedará marcada como «verificada por el usuario».")
                c1, c2, c3 = st.columns([1, 2, 1], vertical_alignment="bottom")
                letter = c1.selectbox("Respuesta", [LETTERS[i] for i in range(len(q.options))], format_func=str.upper, key=f"uk_{q.id}")
                src = c2.text_input("Fuente de la verificación", key=f"us_{q.id}", placeholder="p. ej. corrección en clase 06/10")
                if c3.button("Guardar", key=f"ub_{q.id}", disabled=not src.strip()):
                    userdata.set_user_answer_key(q.id, letter, src.strip())
                    st.success("Guardada. Ya puede aparecer en los test.")
                    st.rerun()
    ukeys = db.query("SELECT * FROM user_answer_keys")
    if ukeys:
        st.subheader("Soluciones introducidas por ti")
        for r in ukeys:
            q = bank.get_question(r["question_id"])
            if not q:
                continue
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"{esc(q.stem[:110])} → **{r['letter'].upper()}** ({esc(r['source'])})")
            if c2.button("Quitar", key=f"rk_{q.id}"):
                userdata.remove_user_answer_key(q.id)
                st.rerun()


def _srs() -> None:
    p = srs.params()
    st.markdown("""
**Cómo funciona el repaso (cajas tipo Leitner):**
- ❌ Fallo → la pregunta vuelve a la **caja 0**: repaso inmediato y prioritario.
- ✅ Acierto → sube una caja; el siguiente repaso se programa según el intervalo de esa caja.
- Acertar a la primera la coloca directamente en la caja indicada abajo.
- Al llegar a la **caja de dominio** se considera dominada; si la vuelves a fallar, regresa a la caja 0.
""")
    with st.form("srs"):
        iv = st.text_input("Intervalos por caja (días, separados por comas)", ",".join(str(x) for x in p["intervals"]))
        c1, c2 = st.columns(2)
        fc = c1.number_input("Caja inicial si aciertas a la primera", 0, 10, int(p["first_correct_box"]))
        mb = c2.number_input("Caja de dominio", 1, 10, int(p["mastery_box"]))
        if st.form_submit_button("Guardar criterios"):
            try:
                ints = [int(x) for x in iv.split(",") if x.strip()]
                assert len(ints) >= 2 and mb < len(ints) and fc < len(ints)
                db.set_setting("srs", {"intervals": ints, "first_correct_box": int(fc), "mastery_box": int(mb)})
                st.success("Criterios guardados.")
            except Exception:
                st.error("Revisa los valores: la caja inicial y la de dominio deben existir en la lista de intervalos.")
    if st.button("Restablecer valores por defecto"):
        db.set_setting("srs", srs.DEFAULTS)
        st.rerun()


def _ai() -> None:
    st.markdown("Las explicaciones **oficiales** (solucionario) y las **citas del temario** funcionan siempre, sin conexión. "
                "Opcionalmente puedes activar explicaciones y resúmenes redactados por IA (Claude), que usan **solo** el texto "
                "de tus documentos y se marcan siempre como «Generado por IA».")
    cur = bool(db.get_setting("ai_enabled", True))
    on = st.toggle("Permitir IA", value=cur)
    if on != cur:  # escribir solo si cambia (cada escritura se sincroniza con la nube)
        db.set_setting("ai_enabled", on)
    has_pkg = explain._sdk_available()
    st.markdown(f"- Paquete `anthropic`: {'✅ instalado' if has_pkg else '❌ no instalado (`pip install anthropic`)'}\n"
                f"- Clave `ANTHROPIC_API_KEY`: {'✅ encontrada' if explain._api_key() else '❌ no configurada'}\n"
                f"- Modelo: `{explain.AI_MODEL}`\n- Estado: {'**activa**' if explain.ai_available() else 'inactiva'}")
    st.caption("Para activarla, crea el archivo `.streamlit/secrets.toml` con la línea `ANTHROPIC_API_KEY = \"...\"` "
               "o define la variable de entorno. Las respuestas se guardan en caché para no repetir llamadas.")


def _backup() -> None:
    c1, c2, c3 = st.columns(3)
    if c1.button("💾 Crear copia de seguridad ahora", width="stretch"):
        p = userdata.backup("manual")
        st.success(f"Copia creada: {p.name}")
    c2.download_button("⬇️ Exportar todo (ZIP)", userdata.export_zip(), file_name=f"oposiciones-{datetime.now():%Y%m%d}.zip",
                       width="stretch", mime="application/zip")
    c3.download_button("⬇️ Estadísticas (Excel)", userdata.export_excel(), file_name=f"estadisticas-{datetime.now():%Y%m%d}.xlsx",
                       width="stretch")
    st.caption(f"Base de datos: `{db.get_db_path()}` · Copias en `{config.BACKUP_DIR}` (se crea una automática al día y se guardan las 20 últimas).")
    bks = userdata.list_backups()
    if bks:
        b = st.selectbox("Restaurar progreso desde una copia", bks, format_func=lambda p: p.name)
        if st.button("Restaurar esta copia"):
            userdata.restore_backup(b)
            st.success("Progreso restaurado (antes se creó una copia del estado actual).")
    up = st.file_uploader("Importar progreso (progreso.json de una exportación)", type=["json"])
    if up and st.button("Importar progreso"):
        userdata.import_progress_json(up.getvalue())
        st.success("Progreso importado.")


def _import() -> None:
    st.markdown(f"""
Para **añadir temas, test, soluciones o teoría** copia los PDF/Word en la carpeta del proyecto
(`{config.DOCS_DIR}`), por ejemplo `Benicasim/TEMA 13/` con:
- el temario (`Tema 13.pdf`), el test (`Test Tema 13.pdf`) y su solucionario (`Soluciones Test Tema 13.pdf`).
- Esquemas en imagen: `Resumen/ANEXO I/TEMA 13/1.png`, `2.png`…

Después pulsa **Reimportar**. Las preguntas ya existentes no se duplican (se identifican por su contenido) y tu progreso se conserva.
Los documentos originales nunca se modifican.
""")
    if st.button("🔄 Reimportar documentos", type="primary"):
        userdata.backup("antes-de-reimportar")
        with st.spinner("Analizando documentos…"):
            inv = ingest.run(verbose=False)
        st.cache_data.clear()
        st.success(f"Importación completada: {inv['preguntas_unicas']} preguntas únicas, {inv['preguntas_verificadas']} verificadas.")


def render() -> None:
    nav.page_header("Banco y ajustes", "Inventario del material, preguntas pendientes, criterios de repaso, IA y copias de seguridad.", "⚙️")
    sync = cloudsync.status()
    if sync:
        if sync["last_error"]:
            st.error(f"☁️ No se pudo guardar el progreso en GitHub ({sync['repo']}): {sync['last_error']}. Se reintentará.")
        else:
            st.caption(f"☁️ Progreso sincronizado con GitHub · último guardado: {sync['last_ok'] or 'pendiente de cambios'}")
    tabs = st.tabs(["📦 Inventario", "⚠️ Pendientes de revisión", "🔁 Repaso", "✨ IA", "💾 Copias y exportación", "📥 Importar"])
    with tabs[0]:
        _inventory()
    with tabs[1]:
        _pending()
    with tabs[2]:
        _srs()
    with tabs[3]:
        _ai()
    with tabs[4]:
        _backup()
    with tabs[5]:
        _import()
