import json
import os
import subprocess
import tempfile

import bpy

from ..utils import ensure_af_root, get_af_root
from .merge import apply_snapshot
from .model import PackageSnapshot
from .stage import (
    append_stage_root,
    expand_stage_keep,
    link_stage_keep,
    remove_stage_root,
    remove_unused_stage_objects,
)
from .vcp import apply_vcp_snapshot

_SNAPSHOT_TIMEOUT_SEC = 120


def _module_name():
    return __package__.split(".")[0]


def _snapshot_expr(outpath):
    module = f"{_module_name()}.core.importing.extract"
    return f"import {module} as m; m.write_snapshot_json({outpath!r})"


def _snapshot_cmd(filepath, outpath):
    return [bpy.app.binary_path, "-b", filepath, "--addons", _module_name(), "--python-exit-code", "1", "--python-expr", _snapshot_expr(outpath)]


def _run_snapshot_dump(filepath, outpath):
    try:
        return subprocess.run(
            _snapshot_cmd(filepath, outpath), capture_output=True, text=True, check=False, timeout=_SNAPSHOT_TIMEOUT_SEC
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Snapshot dump timed out after {_SNAPSHOT_TIMEOUT_SEC} seconds.") from exc


def _load_snapshot(filepath):
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    handle.close()
    try:
        result = _run_snapshot_dump(filepath, handle.name)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "Snapshot dump failed.")
        with open(handle.name, "r", encoding="utf-8") as stream:
            return PackageSnapshot.from_dict(json.load(stream))
    finally:
        os.remove(handle.name) if os.path.exists(handle.name) else None


def _stage_snapshot(filepath, snapshot):
    stage = append_stage_root(filepath, snapshot.root_name)
    if stage.root is None:
        raise RuntimeError(f"Could not append source root '{snapshot.root_name}'.")
    return stage


def _cleanup_stage(stage, keep, scene):
    keep = expand_stage_keep(stage, keep)
    link_stage_keep(keep, scene=scene)
    remove_stage_root(stage)
    remove_unused_stage_objects(stage, keep)


def import_package_from_blend(filepath, context):
    snapshot = _load_snapshot(filepath)
    root = ensure_af_root(context.scene)
    stage = _stage_snapshot(filepath, snapshot)
    result = None
    try:
        result = apply_snapshot(snapshot, stage.root, root, context)
        return result
    finally:
        _cleanup_stage(stage, getattr(result, "kept_objects", ()), context.scene)


def import_vcp_from_blend(filepath, context):
    snapshot = _load_snapshot(filepath)
    root = get_af_root(context.scene)
    if root is None:
        raise RuntimeError("No AnthroForge root found in target file.")
    return apply_vcp_snapshot(snapshot, root, context)
