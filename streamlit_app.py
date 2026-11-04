"""Punto de entrada alternativo (mismo contenido que app.py) para un despliegue limpio en Streamlit Cloud."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
