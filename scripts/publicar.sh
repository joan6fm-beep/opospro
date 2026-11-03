#!/usr/bin/env bash
# Publica en GitHub (joan6fm-beep/opospro, main) los cambios pendientes; Streamlit Cloud se actualiza solo.
# Nunca sube el progreso personal: data/oposiciones.db solo se publica sin datos de usuario.
cd "$(dirname "$0")/.." || exit 0
PY="$LOCALAPPDATA/OposPro/venv/Scripts/python.exe"
[ "$(git branch --show-current)" = "main" ] || exit 0
git add -A -- . ':!data/oposiciones.db' ':!.claude'
"$PY" scripts/publish_db.py || { git reset -q; echo "publicar: error preparando la BD" >&2; exit 0; }
git diff --cached --quiet && exit 0
if ! "$PY" -m pytest -q -x tests >/dev/null 2>&1; then
  git reset -q; echo "publicar: las pruebas fallan; no se publica" >&2; exit 0
fi
date -u +"%Y-%m-%dT%H:%M:%SZ" > static/version.txt && git add static/version.txt
git commit -q -m "Auto: publicación desde VS Code" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push -q origin main && echo "publicar: subido $(git rev-parse --short HEAD)"
