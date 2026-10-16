"""Evaluate regular and branched muscle material patches in their instance frame."""
from dataclasses import replace
import numpy as np
from anthroforge.adapters.deformation.muscles import request_for
from anthroforge.core.topology.flow_patches import branch_grids


def material_patches(root, scene, muscle, role):
    from anthroforge.core.visualization.mirror_rules import effective_rule_for_muscle
    from anthroforge.core.visualization.geometry_instance import mirrored
    from anthroforge.core.vcp.muscle_numeric import execute_muscle_batch
    rule = effective_rule_for_muscle(muscle, {f.id: f for f in root.af_vcp_system.fibers},
                                     {s.id: s for s in root.af_scp_system.scps})
    with mirrored(rule if role == "MIRROR" else None):
        request = replace(request_for(root, scene, muscle), output_domain=None)
        result = execute_muscle_batch((request,), "NATIVE").results[0]
    if result.error: raise ValueError(result.error)
    if hasattr(request, "assembly"): return branch_grids(request.assembly, result), True
    rows, cols = result.row_count, result.column_count
    if min(rows, cols) < 2 or len(result.inflated_vertices) != rows*cols:
        raise ValueError("Muscle has no regular material chart; use explicit FLOW fibers.")
    return (("main", np.asarray(result.inflated_vertices).reshape(rows, cols, 3), False, None),), False
