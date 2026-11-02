# OposPro · Auxiliar Administrativo

Plataforma de estudio para las oposiciones de Auxiliar Administrativo construida **solo** con los documentos
de esta carpeta (Benicasim, Almazora, Caso practico, Resumen). Ninguna pregunta ni solución es inventada.

## Cómo abrirla

Doble clic en **`run.bat`**. La primera vez crea un entorno de Python propio (en `%LOCALAPPDATA%\OposPro\venv`,
fuera de OneDrive) e instala las dependencias; después abre el navegador en <http://localhost:8502>.
Para cerrarla, cierra la ventana negra.

Desde el móvil (misma red Wi‑Fi): doble clic en **`movil.bat`** (antes, `run.bat` una vez). Muestra la IP local del PC
y el enlace completo, `http://<IP-de-tu-PC>:8502`, para escribirlo en el navegador del móvil. Si la app ya está abierta
con `run.bat`, solo muestra el enlace. El PC debe seguir encendido y el progreso se guarda en la misma base de datos.

La app escucha en `0.0.0.0:8502` (ver `.streamlit/config.toml`), así que puede usarse a la vez que otra app de Streamlit
en el puerto 8501.

## Qué hay dentro

| Sección | Para qué sirve |
|---|---|
| Inicio | Resumen de tu progreso, examen pendiente, repaso de hoy y recomendaciones |
| Hacer test | Test originales (orden original) y prácticas aleatorias de 10/20/30/50/todas, falladas, nuevas |
| Test aleatorio | Mezcla de temas, cantidad y tipo de preguntas (nuevas, falladas, difíciles, mezcla inteligente…) |
| Mis fallos | Todas las preguntas falladas, su estado y prácticas específicas |
| Simulacros | Exámenes cronometrados con puntuación configurable (simulación, no criterios oficiales) |
| Estudiar temario | Teoría original por apartados, páginas del PDF, esquemas, resúmenes, conceptos, preguntas y errores |
| Resúmenes | Completo, por apartados, rápido, esquema y **resumen de mis errores** con detección de patrones |
| Mi plan / Estadísticas / Mi progreso / Historial | Recomendaciones basadas en tus datos, gráficos y revisión de exámenes antiguos |
| Banco y ajustes | Inventario, preguntas pendientes, criterios de repaso, IA opcional, copias de seguridad, reimportar |

### Modalidades
* **Práctica**: corrección inmediata con *tu respuesta*, *respuesta correcta (oficial)*, *por qué*, *recuerda* y *fuente*.
* **Examen**: sin soluciones hasta finalizar; nota, tiempo y revisión completa.

Los exámenes se guardan en la base de datos a cada respuesta: si cierras la app, en **Examen en curso** puedes continuarlo.

### Distinción visual de las explicaciones
* <kbd>SOLUCIÓN OFICIAL</kbd> / <kbd>JUSTIFICACIÓN OFICIAL</kbd>: texto literal del solucionario.
* <kbd>CITA LITERAL</kbd> / <kbd>TEXTO ORIGINAL</kbd>: fragmento del temario con documento, apartado y página.
* <kbd>EXTRAÍDO DEL SOLUCIONARIO</kbd>: frase literal seleccionada para «Recuerda».
* <kbd>GENERADO POR IA</kbd>: solo si activas la IA opcional; se redacta exclusivamente con los textos anteriores.

## Material detectado (resumen de `data/INVENTARIO.md`)

* 12 temas (Anexo I temas 1‑10, Anexo II temas 1‑2) + casos prácticos · 102 documentos · 11 test originales.
* 500 preguntas, todas únicas; **474 con solución verificada** (son las que entran en los test).
* 25 preguntas de *Caso practico/Practica 1.pdf* **pendientes**: no hay solucionario en los documentos.
* 1 pregunta excluida: *Test Tema 9*, nº 14 — el propio solucionario dice «B (o también válida legalmente la D)».
* 5 pares de preguntas casi idénticas (Temas 2, 3 y 8): nunca coinciden en un mismo examen.
* Temas 7 y 10 tienen teoría y esquemas, pero no test.

## Repetición espaciada (configurable en *Banco y ajustes*)
Cajas 0‑5 con intervalos de 0, 1, 3, 7, 15 y 30 días. Fallo → caja 0 (repaso inmediato). Acierto → sube una caja.
Acierto a la primera → caja 2. Caja ≥ 4 → dominada. Volver a fallar → caja 0.

## Añadir material nuevo
Copia los PDF o Word en una carpeta, por ejemplo `Benicasim/TEMA 13/` (`Tema 13.pdf`, `Test Tema 13.pdf`,
`Soluciones Test Tema 13.pdf`) y pulsa **Banco y ajustes → Importar → Reimportar**. Las preguntas se identifican por su
contenido: no se duplican y tu progreso se conserva. Los esquemas nuevos van en `Resumen/ANEXO I/TEMA 13/`.
Si un test no tiene solucionario, sus preguntas quedan pendientes; puedes introducir la solución a mano
(indicando la fuente) en *Pendientes de revisión*.

## IA opcional
Crea `.streamlit/secrets.toml` con `ANTHROPIC_API_KEY = "..."` (o la variable de entorno) y ejecuta
`pip install anthropic` (ya está en `requirements.txt`). Usa el modelo `claude-opus-5-5` y guarda las respuestas en caché.
Sin clave, todo funciona igual con las explicaciones oficiales y las citas del temario.

## Datos, copias y exportación
* Base de datos: `data/oposiciones.db` (SQLite). Copia automática diaria en `data/backups/` (se guardan 20).
* Exportar: ZIP (progreso JSON + estadísticas Excel + inventario) o Excel; importar/restaurar desde *Banco y ajustes*.

## Streamlit Cloud
En Streamlit Cloud el disco **no es persistente**: SQLite se borraría en cada reinicio. Antes de publicar habría que
llevar las tablas de usuario a una base de datos externa (p. ej. PostgreSQL gestionado). Toda la persistencia pasa por
`core/db.py`, así que el cambio se concentra en ese módulo. Mientras tanto, usa *Exportar todo* / *Importar progreso*
para llevar tu progreso entre equipos.

## Estructura del código
```
app.py                 navegación y arranque
run.bat / movil.bat    abrir en el PC / enlace para el móvil
core/                  lógica (sin interfaz)
  extract/             lectura de PDF/Word y parsers de test, soluciones y teoría
  ingest.py            inventario, verificación, duplicados, vínculo pregunta↔teoría
  db.py  bank.py  exams.py  srs.py  stats.py  plan.py  summaries.py  explain.py  userdata.py
  catalog.json         nombres cortos de temas y asignación de esquemas
ui/                    tema visual, componentes y páginas (ui/views)
tests/                 39 pruebas automáticas (py -m pytest tests)
data/                  base de datos, inventario y copias (generado)
```
