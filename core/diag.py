"""Diagnóstico del servidor en la nube (sin datos personales): static/diag.json.

Un hilo mide cada pocos segundos memoria, hilos, ficheros abiertos, CPU y la latencia del propio servidor
(petición local a /_stcore/health). Así se distingue un servidor bloqueado de un fallo de red externo.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

_OUT = Path(__file__).resolve().parent.parent / "static" / "diag.json"
_T0 = time.time()
_NAME = "opospro-diag"


def _read(p: str) -> str | None:
    try:
        return Path(p).read_text().strip()
    except Exception:  # noqa: BLE001
        return None


def _proc_status() -> dict:
    out = {}
    for line in (_read("/proc/self/status") or "").splitlines():
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM", "Threads"):
            out[k] = v.strip()
    try:
        out["fds"] = len(os.listdir("/proc/self/fd"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _cgroup() -> dict:
    d = {}
    for k, p in (("mem_now", "/sys/fs/cgroup/memory.current"), ("mem_max", "/sys/fs/cgroup/memory.max"),
                 ("mem_now_v1", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
                 ("mem_max_v1", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
                 ("cpu_max", "/sys/fs/cgroup/cpu.max")):
        v = _read(p)
        if v:
            d[k] = v
    st = _read("/sys/fs/cgroup/cpu.stat")
    if st:
        d["cpu_stat"] = dict(line.split() for line in st.splitlines() if len(line.split()) == 2)
    ev = _read("/sys/fs/cgroup/memory.events")
    if ev:
        d["mem_events"] = dict(line.split() for line in ev.splitlines() if len(line.split()) == 2)
    return d


def _procs() -> dict:
    """Procesos del contenedor (detecta git/ssh colgados o zombis acumulados)."""
    out: dict = {"total": 0, "zombies": 0, "names": {}}
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            st = _read(f"/proc/{pid}/stat")
            if not st:
                continue
            name = st[st.find("(") + 1:st.rfind(")")]
            state = st[st.rfind(")") + 2:st.rfind(")") + 3]
            out["total"] += 1
            out["zombies"] += state == "Z"
            out["names"][name] = out["names"].get(name, 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return out


def _tcp() -> dict:
    """Conexiones TCP por estado (CLOSE_WAIT acumuladas = conexiones mal cerradas)."""
    names = {"01": "ESTABLISHED", "06": "TIME_WAIT", "08": "CLOSE_WAIT", "0A": "LISTEN", "04": "FIN_WAIT1",
             "05": "FIN_WAIT2", "09": "LAST_ACK", "02": "SYN_SENT", "03": "SYN_RECV"}
    out: dict = {}
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in (_read(f) or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) > 3:
                k = names.get(parts[3], parts[3])
                out[k] = out.get(k, 0) + 1
    return out


def _sessions() -> int | None:
    try:
        from streamlit.runtime import Runtime
        return len(Runtime.instance()._session_mgr.list_active_sessions())
    except Exception:  # noqa: BLE001
        return None


def _port() -> int:
    try:
        from streamlit import config
        return int(config.get_option("server.port"))
    except Exception:  # noqa: BLE001
        return 8501


def _loop() -> None:
    probes: list = []
    worst = 0.0
    fails = 0
    n = 0
    while True:
        t = time.time()
        ok = True
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{_port()}/_stcore/health", timeout=30) as r:
                r.read()
        except Exception:  # noqa: BLE001
            ok = False
        dt = round(time.time() - t, 3)
        n += 1
        fails += not ok
        worst = max(worst, dt)
        probes = (probes + [dt])[-30:]
        try:
            info = {"host": socket.gethostname(), "pid": os.getpid(), "uptime_s": int(time.time() - _T0),
                    "updated": time.strftime("%H:%M:%S", time.gmtime()), "self_health": {
                        "n": n, "fails": fails, "worst_s": worst, "last": probes},
                    "sessions": _sessions(), "threads": [t.name for t in threading.enumerate()],
                    "proc": _proc_status(), "cgroup": _cgroup(), "procs": _procs(), "tcp": _tcp(),
                    "load": _read("/proc/loadavg")}
            _OUT.parent.mkdir(exist_ok=True)
            tmp = _OUT.with_suffix(".tmp")
            tmp.write_text(json.dumps(info), encoding="utf-8")
            os.replace(tmp, _OUT)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)


def start() -> None:
    if os.name == "nt" or any(t.name == _NAME for t in threading.enumerate()):
        return
    threading.Thread(target=_loop, daemon=True, name=_NAME).start()
