"""OposPro · Auxiliar Administrativo — punto de entrada de Streamlit.

Ejecutar:  streamlit run app.py   (o doble clic en run.bat)
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="OposPro · Auxiliar Administrativo", page_icon="📘", layout="wide",
                   initial_sidebar_state="auto")

from core import cloudsync, db, diag, userdata  # noqa: E402

diag.start()
from ui import nav, theme  # noqa: E402
from ui.views import (ajustes, estadisticas, examen, fallos, favoritas, historial, inicio, plan_view,  # noqa: E402
                      resumenes, simulacros, temario, test_aleatorio, test_tema)

theme.inject()
theme.plotly_template()


def _password_gate() -> None:
    """Contraseña de acceso si existe el secret APP_PASSWORD (p. ej. en Hugging Face, app pública)."""
    import hmac
    import os
    pwd = os.environ.get("APP_PASSWORD")
    if not pwd:
        try:
            pwd = st.secrets.get("APP_PASSWORD")
        except Exception:  # noqa: BLE001 - sin secrets.toml
            pwd = None
    if not pwd or st.session_state.get("_auth_ok"):
        return
    st.markdown("### 📘 OposPro")
    with st.form("login"):
        given = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(given.encode(), str(pwd).encode()):
                st.session_state["_auth_ok"] = True
                st.rerun()
            st.error("Contraseña incorrecta")
    st.stop()


_password_gate()


@st.cache_resource(show_spinner="Preparando el banco de preguntas (solo la primera vez)…")
def _bootstrap() -> bool:
    if db.bank_is_empty():
        from core import ingest  # solo si falta el banco: importa PyMuPDF (lento y pesado)
        ingest.run(verbose=False)
    return True


_bootstrap()
# nube: descarga el progreso en segundo plano (la página se muestra sin esperar a GitHub);
# también activa la sincronización si los secrets se guardan con la app ya en marcha
cloudsync.start(background=True)
if "_daily_backup" not in st.session_state:
    try:
        userdata.auto_daily_backup()
    except Exception:  # noqa: BLE001 - la copia nunca debe impedir abrir la app
        pass
    st.session_state["_daily_backup"] = True

RENDERERS = {}


def R(key, page_fn, **kw):
    RENDERERS[key] = page_fn
    return nav.register(key, st.Page(page_fn, **kw))


pages = {
    "": [
        R("inicio", inicio.render, title="Inicio", icon="🏠", default=True),
        R("examen", examen.render, title="Examen en curso", icon="▶️", url_path="examen"),
    ],
    "Practicar": [
        R("tema", test_tema.render, title="Hacer test", icon="📝", url_path="test"),
        R("aleatorio", test_aleatorio.render, title="Test aleatorio", icon="🎲", url_path="aleatorio"),
        R("fallos", fallos.render, title="Mis fallos", icon="❌", url_path="fallos"),
        R("simulacros", simulacros.render, title="Simulacros", icon="⏱️", url_path="simulacros"),
        R("favoritas", favoritas.render, title="Favoritas", icon="⭐", url_path="favoritas"),
    ],
    "Estudiar": [
        R("temario", temario.render, title="Estudiar temario", icon="📚", url_path="temario"),
        R("resumenes", resumenes.render, title="Resúmenes", icon="🧾", url_path="resumenes"),
    ],
    "Mi evolución": [
        R("plan", plan_view.render, title="Mi plan de estudio", icon="🗓️", url_path="plan"),
        R("estadisticas", estadisticas.render, title="Estadísticas", icon="📊", url_path="estadisticas"),
        R("progreso", estadisticas.render_progress, title="Mi progreso", icon="📈", url_path="progreso"),
        R("historial", historial.render, title="Historial", icon="📜", url_path="historial"),
    ],
    "Sistema": [
        R("ajustes", ajustes.render, title="Banco y ajustes", icon="⚙️", url_path="ajustes"),
    ],
}

with st.sidebar:
    st.markdown("### 📘 OposPro")
    st.caption("Auxiliar Administrativo · Benicàssim")
    nav.sync_badge()

selected = st.navigation(pages, position="sidebar", expanded=True)
_sync = cloudsync.status()
if _sync["pulling"] and not _sync["last_error"]:
    nav.wait_for_sync()  # unos segundos: así nada se guarda antes de recuperar el progreso
    st.stop()
# Gancho para las pruebas automáticas (AppTest no puede navegar a páginas definidas como funciones)
forced = st.session_state.get("_test_page")
if forced in RENDERERS:
    RENDERERS[forced]()
else:
    selected.run()
