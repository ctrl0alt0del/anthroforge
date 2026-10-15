"""Main-thread capture and revision stamps for final-skin worker requests."""
from dataclasses import asdict
from pathlib import Path
import numpy as np
from . import storage
from .publication import compatible, mesh_identity
from .capture import capture_anatomy
from ...core.deformation.reference import DeformationSettings, canonical
from ...core.deformation.validation import validate_anatomy, validate_mesh_identity
from ...core.deformation.scheduling import Revision
from ...core.warnings import session


def settings(root):
    return asdict(DeformationSettings(method=root.af_topology_settings.deformation_method))


def construction_signature(root):
    import hashlib
    value = root.af_draft_skin_settings
    fields = ("gap_limit_percent","gap_strength_percent","minimum_offset_percent", "collagen_depth_percent",
              "collagen_core_percent","collagen_falloff_percent")
    values = {key:getattr(value,key) for key in fields}
    topology = root.af_topology_settings
    values.update(quads=topology.target_quad_count,symmetry=topology.symmetry_mode,origin=tuple(topology.custom_origin),
        normal=tuple(topology.custom_normal),refinement=topology.refinement_strategy,gaps=gap_settings(root))
    return hashlib.sha256(canonical(values)).hexdigest()


def gap_settings(root):
    groups = [root.af_scp_system.scps]
    groups.extend(getattr(root.af_vcp_system,key,()) for key in ("muscles","fibers","blobs","soft_tissues"))
    return [(item.id,item.skin_gap_mode,item.skin_gap_limit_percent,item.skin_gap_strength_percent)
            for group in groups for item in group if hasattr(item,"skin_gap_mode")]


def revision(root):
    block = root.get(storage.KEY)
    signature = block.get("af_content_signature","") if hasattr(block,"get") else ""
    return Revision(session.EPOCH,signature,canonical(settings(root)),str(session.CHANGES.get(session.id_token(root),0)))


def topology(root, scene):
    from ..topology.warm import _topology
    associated = root.get("af_deformation_mesh")
    if associated is not None:
        if associated.get("af_deformation_root") != root or associated.name not in scene.objects:
            raise ValueError("Final skin ownership changed; initialize the duplicated/imported root explicitly.")
        return associated
    return _topology(root,scene)


def prepare(context, root, spec):
    from ...core.deformation.serialization import encode
    from ...core.topology.protocol import write_result
    from ..warm_update.current_output import current_topology_result
    obj = topology(root,context.scene); compatible(obj); reference = storage.load(root,obj)
    validate_mesh_identity(reference,*mesh_identity(obj))
    records, points, faces = capture_anatomy(root,context.scene,context.evaluated_depsgraph_get())
    targets = validate_anatomy(reference,records,points)
    save_anatomy(spec,records,points,faces)
    Path(spec.job_dir,"reference.txt").write_text(encode(reference),encoding="ascii")
    np.savez(Path(spec.job_dir,"targets.npz"),targets=targets)
    write_result(spec.current_topology_path,current_topology_result(root,context.scene,obj))


def save_anatomy(spec, records, points, faces):
    from .initialization import pack_sources
    arrays = {}; pack_sources(arrays,records,points,faces)
    np.savez(Path(spec.job_dir,"current_anatomy.npz"),**arrays)
