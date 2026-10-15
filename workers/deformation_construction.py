"""Prepare the final-skin reference before a newly generated topology is published."""
from dataclasses import asdict
from pathlib import Path
import bpy
import numpy as np
from anthroforge.adapters.deformation.capture import capture_anatomy
from core.deformation.reference import DeformationSettings
from core.deformation.serialization import encode, decode
from workers.deformation_reference import build
from types import SimpleNamespace


def prepare(spec, result, capture):
    root = bpy.context.scene.objects[spec.root_name]
    records, points, faces = capture_anatomy(root,bpy.context.scene,bpy.context.evaluated_depsgraph_get())
    source = dict(surface_vertices=capture.vertices,surface_faces=capture.triangles,
        plane=np.zeros(6) if capture.plane is None else np.concatenate((capture.plane.origin,capture.plane.normal)))
    for i,row in enumerate(records): source.update({f"points_{i}":points[row["key"]],f"faces_{i}":faces[row["key"]]})
    settings = DeformationSettings(method=root.af_topology_settings.deformation_method)
    adapted = SimpleNamespace(cancel_path=spec.cancel_path,topology_update=dict(settings=asdict(settings)))
    reference = build(adapted,result,records,source); payload = encode(reference)
    if decode(payload).signature != reference.signature: raise ValueError("Reference serialization failed.")
    Path(spec.job_dir,"reference.txt").write_text(payload,encoding="ascii")


def attempt(spec, result, capture):
    try: prepare(spec,result,capture)
    except Exception as error:
        if Path(spec.cancel_path).exists(): raise
        result.statistics.setdefault("warnings",[]).append("Deformation reference preparation failed: "+str(error))
        result.statistics["deformation_preparation_error"] = str(error)
