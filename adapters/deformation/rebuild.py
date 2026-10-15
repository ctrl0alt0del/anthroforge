"""Explicit full reconstruction uses existing workers and prepares replacement before publication."""
import json
from pathlib import Path
import numpy as np
from .capture import capture_anatomy
from .initialization import pack_sources
from ..warm_update.capture import prepare_array_job


def capture(context, root, spec):
    prepare_array_job(context,root,spec)
    records, points, faces = capture_anatomy(root,context.scene,context.evaluated_depsgraph_get())
    arrays = {}; pack_sources(arrays,records,points,faces)
    np.savez(Path(spec.job_dir,"rebuild_anatomy.npz"),**arrays)
    Path(spec.job_dir,"contributors.json").write_text(json.dumps(records),encoding="utf-8")
