"""Prepare the final-skin reference before a newly generated topology is published."""
from dataclasses import asdict
from pathlib import Path
import bpy
import numpy as np
from anthroforge.adapters.deformation.capture import capture_anatomy
from core.deformation.reference import DeformationSettings
from core.deformation.serialization import decode
import json
from core.topology.process import execute
from core.topology.protocol import write_result


def prepare(spec, result, capture):
    root = bpy.context.scene.objects[spec.root_name]
    records, points, faces = capture_anatomy(root,bpy.context.scene,bpy.context.evaluated_depsgraph_get())
    source = dict(surface_vertices=capture.vertices,surface_faces=capture.triangles,
        plane=np.zeros(6) if capture.plane is None else np.concatenate((capture.plane.origin,capture.plane.normal)))
    for i,row in enumerate(records): source.update({f"points_{i}":points[row["key"]],f"faces_{i}":faces[row["key"]]})
    settings = DeformationSettings(method=root.af_topology_settings.deformation_method)
    folder = Path(spec.job_dir); write_result(folder/"reference_input.npz", result)
    np.savez(folder/"reference_source.npz", **source)
    (folder/"reference_request.json").write_text(json.dumps(dict(records=records,settings=asdict(settings),cancel=spec.cancel_path)))
    _run_preparation(folder, spec.cancel_path)


def _run_preparation(folder, cancel_path):
    worker = Path(__file__).with_name("deformation_prepare_worker.py")
    reference = folder/"reference.txt"
    if reference.exists(): reference.unlink()
    status = execute([bpy.app.binary_path,"--factory-startup","-b","--python",worker,"--",folder],
                     folder,"reference_prepare",lambda: Path(cancel_path).exists(),600)
    if status["exit_code"] or not reference.exists():
        raise RuntimeError(f"Reference preparation failed; see {folder/'reference_prepare.log'}")
    decode(reference.read_text(encoding="ascii"))


def attempt(spec, result, capture):
    try: prepare(spec,result,capture)
    except Exception as error:
        if Path(spec.cancel_path).exists(): raise
        result.statistics.setdefault("warnings",[]).append("Deformation reference preparation failed: "+str(error))
        result.statistics["deformation_preparation_error"] = str(error)
