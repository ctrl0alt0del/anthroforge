"""Read-only benchmark for shortcut/depsgraph feedback in a loaded blend."""

import argparse
import json
from pathlib import Path
import sys
import time
import traceback

import bpy

from anthroforge.core.deps.runtime_trace import (
    clear_request_telemetry, request_telemetry, set_request_telemetry)
from anthroforge.core.utils import get_af_root
from anthroforge.core.visualization import sync_runner
from anthroforge.properties import vcp_properties


_MANUAL_CALLS = []
_SYNC_CONTEXT = vcp_properties.sync_context
_SYNC_RUNNER = sync_runner.sync_from_dirty_hints


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shortcut", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--events", type=int, default=5)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _shortcut(root, name):
    rows = root.af_shortcut_system.shortcuts
    return next((row for row in rows if str(row.name) == name), None)


def _pending_count():
    return len(sync_runner._PENDING) + len(sync_runner._TAIL_PENDING)


def _force_ready():
    for item in sync_runner._PENDING:
        item.due_at = 0.0


def _flush_runtime():
    started = time.perf_counter(); passes = 0
    while _pending_count() and passes < 16:
        _force_ready(); sync_runner._flush_pending(); passes += 1
    return 1000.0 * (time.perf_counter() - started), passes


def _cycle(index):
    started = time.perf_counter(); bpy.context.view_layer.update()
    update_ms = 1000.0 * (time.perf_counter() - started)
    queued = _pending_count(); flush_ms, passes = _flush_runtime()
    return {"index": index, "update_ms": update_ms, "queued": queued,
            "flush_ms": flush_ms, "passes": passes, "remaining": _pending_count()}


def _apply(row):
    value = float(row.proxy_float); started = time.perf_counter()
    row.proxy_float = value * 1.01 if value else 0.01
    return value, float(row.proxy_float), 1000.0 * (time.perf_counter() - started)


def _traced_sync(context, dirty_hints=None, **kwargs):
    if len(_MANUAL_CALLS) < 4:
        _MANUAL_CALLS.append({"hints": repr(dirty_hints),
                              "stack": traceback.format_stack(limit=12)})
    return _SYNC_CONTEXT(context, dirty_hints=dirty_hints, **kwargs)


def _install_tracer():
    names = ("anthroforge.properties.vcp_properties", "properties.vcp_properties")
    for name in names:
        module = sys.modules.get(name)
        if module is not None:
            module.sync_context = _traced_sync
    sync_runner.sync_from_dirty_hints = _traced_runner


def _traced_runner(*args, **kwargs):
    if kwargs.get("source", "manual") == "manual" and len(_MANUAL_CALLS) < 4:
        _MANUAL_CALLS.append({"hints": repr(kwargs.get("dirty_hints")),
                              "stack": traceback.format_stack(limit=12)})
    return _SYNC_RUNNER(*args, **kwargs)


def _result(args, root, row):
    before, after, apply_ms = _apply(row)
    cycles = [_cycle(index) for index in range(args.events)]
    return {"file": bpy.data.filepath, "root": root.name, "shortcut": row.name,
            "before": before, "after": after, "apply_ms": apply_ms,
            "cycles": cycles, "manual_calls": _MANUAL_CALLS,
            "telemetry": list(request_telemetry(clear=True))}


def main():
    args = _arguments(); root = get_af_root(bpy.context.scene)
    row = None if root is None else _shortcut(root, args.shortcut)
    if row is None:
        raise RuntimeError(f"Shortcut not found: {args.shortcut}")
    _install_tracer()
    set_request_telemetry(True); clear_request_telemetry()
    result = _result(args, root, row)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("AF_SHORTCUT_FEEDBACK", json.dumps(result), flush=True)


main()
