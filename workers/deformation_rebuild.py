import json
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
import numpy as np
from core.deformation.reference import DeformationSettings
from core.deformation.serialization import encode
from workers.deformation_reference import build


def prepare(spec, topology, skin, capture):
    if not Path(spec.job_dir,"rebuild_anatomy.npz").exists(): return
    try:
        records = json.loads(Path(spec.job_dir,"contributors.json").read_text(encoding="utf-8"))
        with np.load(Path(spec.job_dir,"rebuild_anatomy.npz"),allow_pickle=False) as archive: source = dict(archive)
        source.update(surface_vertices=skin.vertices,surface_faces=skin.triangles,
            plane=np.zeros(6) if capture.plane is None else np.concatenate((capture.plane.origin,capture.plane.normal)))
        adapted = SimpleNamespace(cancel_path=spec.cancel_path,topology_update=dict(settings=asdict(DeformationSettings())))
        reference = build(adapted,topology,records,source)
        Path(spec.job_dir,"reference.txt").write_text(encode(reference),encoding="ascii")
    except Exception as error:
        topology.statistics["deformation_preparation_error"] = str(error)
        topology.statistics.setdefault("warnings",[]).append("Reference preparation failed: "+str(error))
