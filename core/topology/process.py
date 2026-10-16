"""Bounded native subprocesses, cancellation and retained stage diagnostics."""
import ctypes as C
import json
import os
import subprocess
import time
from pathlib import Path
from .status import check_cancelled


class Counters(C.Structure):
    _fields_ = [("cb", C.c_ulong), ("faults", C.c_ulong)] + [(name, C.c_size_t) for name in
        ("peak", "working", "quota_peak", "quota", "nonpaged_peak", "nonpaged", "pagefile", "pagefile_peak")]


def memory(process):
    if os.name != "nt": return 0
    counters = Counters(); counters.cb = C.sizeof(counters)
    query = C.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [C.c_void_p, C.c_void_p, C.c_ulong]
    return counters.peak if query(int(process._handle), C.byref(counters), counters.cb) else 0


def terminate_tree(process):
    if process.poll() is not None: return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    else: process.kill()
    process.wait(timeout=15)


def monitor(process, cancelled, timeout, budget):
    start = time.monotonic(); peak = 0
    try:
        while process.poll() is None:
            check_cancelled(cancelled); peak = max(peak, memory(process))
            if time.monotonic() - start > timeout: raise RuntimeError("Topology native stage exceeded its time budget.")
            if peak > budget: raise MemoryError("Topology native stage exceeded its memory budget.")
            time.sleep(.1)
        check_cancelled(cancelled)
        return dict(exit_code=process.returncode, seconds=time.monotonic()-start, peak_rss=peak)
    finally:
        if process.poll() is None: terminate_tree(process)


def execute(command, folder, name, cancelled=None, timeout=600, budget=6*1024**3, cwd=None):
    log = Path(folder) / (name + ".log")
    with log.open("w", encoding="utf-8") as stream:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(list(map(str, command)), cwd=cwd, stdout=stream,
                                   stderr=subprocess.STDOUT, creationflags=flags)
        result = monitor(process, cancelled, timeout, budget)
    (Path(folder)/(name+".json")).write_text(json.dumps(result), encoding="utf-8")
    return result
