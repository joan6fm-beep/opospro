"""Rutas y parámetros globales de la aplicación."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Carpeta con los documentos originales (solo lectura). Por defecto, la raíz del proyecto.
DOCS_DIR = Path(os.environ.get("OPOS_DOCS_DIR", ROOT))

# Subcarpetas del proyecto que NO contienen material de estudio.
EXCLUDED_DIRS = {"core", "ui", "data", "tests", ".venv", "venv", "__pycache__", ".git", ".streamlit", "views"}

DATA_DIR = Path(os.environ.get("OPOS_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("OPOS_DB_PATH", DATA_DIR / "oposiciones.db"))
BACKUP_DIR = DATA_DIR / "backups"
CACHE_DIR = DATA_DIR / "cache"
INVENTORY_JSON = DATA_DIR / "inventario.json"
INVENTORY_MD = DATA_DIR / "INVENTARIO.md"
ESQUEMAS_MAP = DATA_DIR / "esquemas_map.json"

for _d in (DATA_DIR, BACKUP_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

APP_NAME = "OposPro · Auxiliar Administrativo"
