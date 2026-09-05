"""Read-only real-file Python/native Muscle numerical parity benchmark."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--file", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--value", type=float, default=7.0)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _register():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"): anthroforge.register()


def _root():
    from anthroforge.core.utils import get_af_root
    return get_af_root(bpy.context.scene)


def _apply_shortcut(root, value):
    shortcut = next(row for row in root.af_shortcut_system.shortcuts if row.name == "Cranium Lobe Width")
    shortcut.proxy_float = float(value)


def _capture(root):
    from anthroforge.core.visualization.muscle_numeric_runtime import capture_muscle_work
    from anthroforge.core.visualization.muscle_sync import register_muscle_sync
    sync, scene, vcp = register_muscle_sync(), bpy.context.scene, root.af_vcp_system
    vis = sync._get_vis_collection(scene)
    return tuple(capture_muscle_work(sync, vis, root, scene, vcp, row) for row in vcp.muscles)


def _run_backend(work, backend):
    from anthroforge.core.vcp.muscle_numeric import execute_muscle_batch
    requests = tuple(row.request for row in work if row.request is not None)
    return execute_muscle_batch(requests, backend)


def _delta(first, second):
    if first.shape != second.shape: return float("inf")
    return float(np.max(np.abs(first - second))) if first.size else 0.0


def _comparisons(python, native):
    return tuple(_comparison(left, right) for left, right in zip(python.results, native.results))


def _comparison(left, right):
    return {"muscle_id": left.muscle_id, "base_max_abs": _delta(left.base_vertices, right.base_vertices),
            "inflated_max_abs": _delta(left.inflated_vertices, right.inflated_vertices),
            "faces_equal": bool(np.array_equal(left.faces, right.faces)), "points": len(left.base_vertices)}


def _summary(args, before):
    root = _root(); _apply_shortcut(root, args.value); work = _capture(root)
    python, native = _run_backend(work, "PYTHON"), _run_backend(work, "NATIVE")
    rows = _comparisons(python, native)
    return {"source_hash": before, "source_unchanged": before == _hash(args.file),
            "python_ms": python.elapsed_ms, "native_ms": native.elapsed_ms,
            "native_workers": native.workers, "native_parallel": native.parallel,
            "muscles": len(rows), "total_points": sum(row["points"] for row in rows),
            "max_base_abs": max(row["base_max_abs"] for row in rows),
            "max_inflated_abs": max(row["inflated_max_abs"] for row in rows),
            "faces_equal": all(row["faces_equal"] for row in rows), "comparisons": rows}


def main():
    args = _args(); before = _hash(args.file); _register(); bpy.ops.wm.open_mainfile(filepath=args.file)
    result = _summary(args, before); Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("AF_MUSCLE_NUMERIC_BENCH", json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
