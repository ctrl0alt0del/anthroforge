"""Blender orchestration for anatomy-guided native quad generation."""
import json
import sys
try:
    from ...core.native_platform import python_executable
except ImportError:
    from core.native_platform import python_executable
import tempfile
from pathlib import Path
import numpy as np
from .engine import guides, instant
try:
    from ...core.topology.process import execute
except ImportError:
    from core.topology.process import execute


def clipped_paths(capture):
    paths = []
    for guide in capture.flow_guides:
        points = np.asarray(guide.points)
        keep = np.ones(len(points), bool) if capture.plane is None else (points-capture.plane.origin) @ capture.plane.normal < -1e-8
        indices = np.flatnonzero(keep)
        for run in np.split(indices, np.flatnonzero(np.diff(indices) > 1)+1):
            if len(run) >= 2: paths.append(points[run])
    return paths


def remesh(capture, work, anchors, target, cancelled, update=None):
    plane = None if capture.plane is None else instant.SymmetryPlane(capture.plane.origin, capture.plane.normal)
    if plane is not None: instant.bisect_left_half(work, plane)
    v, f, _ = guides.mesh_arrays(work); f = instant.cut_guide_holes(v, f, anchors, plane)
    folder = Path(tempfile.mkdtemp(prefix="af_quadwild_")); paths = clipped_paths(capture)
    source, output = folder/"input.npz", folder/"result.npz"
    np.savez(source, vertices=v, faces=f, flow_samples=capture.flow_samples if capture.flow_samples is not None else np.empty((0, 10)),
             flow_points=np.vstack(paths) if paths else np.empty((0, 3)), flow_offsets=np.r_[0, np.cumsum([len(p) for p in paths])].astype(np.int64))
    worker = Path(__file__).resolve().parents[2]/"workers/topology_quadwild_worker.py"
    count = max(64, round(target/(2 if plane is not None else 1)))
    run = execute([python_executable(), worker, source, output, count], folder, "worker", progress(folder, cancelled, update), 1800)
    if run["exit_code"]: raise RuntimeError(f"QuadWild worker failed; previous output retained. Diagnostic: {folder/'worker.log'}")
    with np.load(output, allow_pickle=False) as d: v, f, stats = d["vertices"].copy(), d["faces"].copy(), json.loads(str(d["statistics"]))
    if plane is not None: v, f = instant.mirrored_output(v, f, anchors, plane)
    return v, f, dict(stats, worker=run, diagnostic=str(folder/"worker.log"))


def progress(folder, cancelled, update):
    last = []
    def check():
        try: value = json.loads((folder/"progress.json").read_text())
        except (OSError, ValueError): value = None
        if value is not None and value != last:
            last[:] = value
            if update: update(*value)
        return cancelled is not None and cancelled()
    return check
