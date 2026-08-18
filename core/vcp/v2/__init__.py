"""Blender-independent accepted Fiber Solver V2 APIs."""

from importlib import import_module

from .contracts import (
    V2_CONTRACT_VERSION,
    V2_ENGINE_VERSION,
    V2Anchor,
    V2AnchorRole,
    V2ArrayColliderSnapshot,
    V2ColliderSnapshot,
    V2CollisionPolicy,
    V2Diagnostics,
    V2Quality,
    V2Request,
    V2ResolvedTolerances,
    V2Result,
    V2Settings,
    V2Termination,
    V2Topology,
    decode_request,
    decode_result,
    encode_contract,
    stable_contract_signature,
)
from .structural import (
    DEFAULT_STRUCTURAL_CACHE,
    StructuralFactorCache,
    V2_STRUCTURAL_VERSION,
    V2StructuralEnergy,
    V2StructuralResult,
    clear_structural_cache,
    solve_structural,
    structural_cache_stats,
    structural_energy,
    structural_gradient,
    structural_stationarity,
)
from .contact_structural import (
    DEFAULT_CONTACT_FACTOR_CACHE,
    V2_CONTACT_STRUCTURAL_VERSION,
    ContactSlotEnergy,
    ContactStructuralResult,
    assemble_contact_matrix,
    clear_contact_factor_cache,
    contact_factor_cache_stats,
    contact_slot_energy,
    contact_stationarity,
    solve_contact_structural,
)
from .contact_sampled import (
    DEFAULT_SAMPLED_CONTACT_CACHE,
    DEFAULT_SAMPLE_FACTORS,
    V2_SAMPLED_CONTACT_VERSION,
    SampledContactResult,
    assemble_sampled_contact_matrix,
    clear_sampled_contact_cache,
    sample_edge_points,
    sampled_contact_cache_stats,
    sampled_contact_energy,
    sampled_contact_stationarity,
    solve_sampled_contact,
)
from .contact_unilateral import (
    V2_UNILATERAL_CONTACT_VERSION,
    UnilateralConstraint,
    UnilateralContactResult,
    solve_unilateral_contact,
)
from .collision import (
    EDGE_BATCH,
    PAIR_BATCH,
    V2_COLLISION_VERSION,
    V2BackendStatus,
    V2CollisionReason,
    V2CollisionWorkload,
    V2DistanceCertificateCache,
    V2OwnerContact,
    V2NativeCollisionWorld,
    V2SafeStep,
    V2SegmentBatch,
    V2StaticClearance,
    V2TriangleSnapshot,
    build_native_collision_world_batch,
    build_triangle_snapshot,
    build_triangle_snapshot_known,
    build_native_collision_world,
    cached_known_triangle_snapshot,
    cached_native_collision_world,
    cached_native_collision_world_batch,
    cached_triangle_snapshot,
    clear_triangle_snapshot_cache,
    clear_native_collision_world_cache,
    collision_backend_status,
    collision_free_step,
    point_triangle_distances,
    probe_collision_workload,
    segment_triangle_distances,
    validate_static_clearance,
    validate_segment_clearance_batch,
    triangle_snapshot_cache_stats,
)
from .planner import (
    V2_PLANNER_41_VERSION,
    V2_PLANNER_42_VERSION,
    V2_PLANNER_43_VERSION,
    V2_PLANNER_VERSION,
    V2PlannerDiagnostics,
    V2PlannerBranch,
    V2PlannerMode,
    V2PlannerResult,
    V2PlannerSpan,
    plan_reference,
    plan_reference_v41,
    plan_reference_v42,
    plan_reference_v43,
)
from .solver import (
    DEFAULT_CONTACT_WEIGHT,
    V2_SOLVER_P5_VERSION,
    V2_SOLVER_P51_VERSION,
    V2Package5Result,
    V2Package5Trace,
    solve_package5,
    solve_package51,
)
from .solver_p6 import V2_SOLVER_P6_VERSION, V2Package6Trace, solve_package6
from .solver_p61 import V2_SOLVER_P61_VERSION, V2Package61Trace, solve_package61
from .solver_v21 import (V2_SOLVER_V21_VERSION, V21Trace, clear_v21_route_cache,
                         solve_v21, v21_route_cache_stats)
from .solver_v22 import (V2_SOLVER_V22_VERSION, V22Trace, clear_v22_route_cache,
                         solve_v22, v22_request_signature, v22_route_cache_stats,
                         v22_snapshot_key)
from .solver_v23 import (V2_SOLVER_V23_VERSION, V23Trace, clear_v23_route_cache,
                         solve_v23, v23_route_cache_stats)
from .solver_v24 import (V2_SOLVER_V24_VERSION, V24Trace, clear_v24_route_cache,
                         solve_v24, v24_route_cache_stats)
from .solver_pin_smoothing import (PIN_SMOOTHING_VERSION, PinSmoothingTrace,
                                   solve_pin_smoothing)
from .production import (V2_ACCEPTED_FEATURES, V2_PRODUCTION_VERSION,
                         clear_v2_production_caches, solve_v2,
                         v2_backend_status, v2_production_cache_stats)


_EXPERIMENTAL_EXPORTS = {
    "V2_SOLVER_V25_BRANCH2_VERSION": "solver_v25_branch2", "V25Branch2Trace": "solver_v25_branch2",
    "solve_v25_branch2": "solver_v25_branch2", "V2_SOLVER_P71_VERSION": "solver_p71",
    "V2Package71Trace": "solver_p71", "solve_package71": "solver_p71",
    "V2_SOLVER_P72_VERSION": "solver_p72", "V2Package72Trace": "solver_p72",
    "solve_package72": "solver_p72", "V2_SOLVER_P8_VERSION": "solver_p8",
    "V2Package8Trace": "solver_p8", "solve_package8": "solver_p8",
    "V2_SOLVER_P81_VERSION": "solver_p81", "V2Package81Trace": "solver_p81",
    "solve_package81": "solver_p81", "V2_SOLVER_P82_VERSION": "solver_p82",
    "V2Package82Trace": "solver_p82", "solve_package82": "solver_p82",
}


def __getattr__(name):
    module = _EXPERIMENTAL_EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value

__all__ = (
    "V2_CONTRACT_VERSION", "V2_ENGINE_VERSION", "V2Anchor",
    "V2AnchorRole", "V2ArrayColliderSnapshot", "V2ColliderSnapshot", "V2CollisionPolicy",
    "V2Diagnostics", "V2Quality", "V2Request",
    "V2ResolvedTolerances", "V2Result", "V2Settings",
    "V2Termination", "V2Topology", "decode_request", "decode_result",
    "encode_contract", "stable_contract_signature",
    "DEFAULT_STRUCTURAL_CACHE", "StructuralFactorCache",
    "V2_STRUCTURAL_VERSION", "V2StructuralEnergy", "V2StructuralResult",
    "clear_structural_cache", "solve_structural", "structural_cache_stats",
    "structural_energy", "structural_gradient", "structural_stationarity",
    "DEFAULT_CONTACT_FACTOR_CACHE", "V2_CONTACT_STRUCTURAL_VERSION",
    "ContactSlotEnergy", "ContactStructuralResult", "assemble_contact_matrix",
    "clear_contact_factor_cache", "contact_factor_cache_stats", "contact_slot_energy",
    "contact_stationarity", "solve_contact_structural",
    "EDGE_BATCH", "PAIR_BATCH", "V2_COLLISION_VERSION",
    "V2BackendStatus", "V2CollisionReason", "V2CollisionWorkload", "V2DistanceCertificateCache", "V2OwnerContact", "V2NativeCollisionWorld",
    "V2SafeStep", "V2StaticClearance", "V2TriangleSnapshot",
    "V2SegmentBatch",
    "build_triangle_snapshot", "build_triangle_snapshot_known", "build_native_collision_world",
    "build_native_collision_world_batch", "collision_backend_status",
    "cached_native_collision_world", "cached_native_collision_world_batch",
    "cached_known_triangle_snapshot", "clear_native_collision_world_cache",
    "cached_triangle_snapshot", "clear_triangle_snapshot_cache",
    "collision_free_step", "point_triangle_distances", "probe_collision_workload",
    "segment_triangle_distances", "validate_static_clearance",
    "validate_segment_clearance_batch",
    "triangle_snapshot_cache_stats",
    "V2_PLANNER_VERSION", "V2_PLANNER_41_VERSION", "V2_PLANNER_42_VERSION", "V2_PLANNER_43_VERSION",
    "V2PlannerDiagnostics", "V2PlannerBranch", "V2PlannerMode", "V2PlannerResult",
    "V2PlannerSpan",
    "plan_reference", "plan_reference_v41", "plan_reference_v42", "plan_reference_v43",
    "DEFAULT_CONTACT_WEIGHT", "V2_SOLVER_P5_VERSION", "V2_SOLVER_P51_VERSION",
    "V2Package5Result", "V2Package5Trace", "solve_package5", "solve_package51",
    "V2_SOLVER_P6_VERSION", "V2Package6Trace", "solve_package6",
    "V2_SOLVER_P61_VERSION", "V2Package61Trace", "solve_package61",
    "V2_SOLVER_V21_VERSION", "V21Trace", "clear_v21_route_cache",
    "solve_v21", "v21_route_cache_stats",
    "V2_SOLVER_V22_VERSION", "V22Trace", "clear_v22_route_cache",
    "solve_v22", "v22_request_signature", "v22_route_cache_stats", "v22_snapshot_key",
    "V2_SOLVER_V23_VERSION", "V23Trace", "clear_v23_route_cache",
    "solve_v23", "v23_route_cache_stats",
    "V2_SOLVER_V24_VERSION", "V24Trace", "clear_v24_route_cache",
    "solve_v24", "v24_route_cache_stats",
    "PIN_SMOOTHING_VERSION", "PinSmoothingTrace", "solve_pin_smoothing",
    "V2_SAMPLED_CONTACT_VERSION", "DEFAULT_SAMPLED_CONTACT_CACHE", "DEFAULT_SAMPLE_FACTORS",
    "SampledContactResult", "assemble_sampled_contact_matrix", "clear_sampled_contact_cache",
    "sample_edge_points", "sampled_contact_cache_stats", "sampled_contact_energy",
    "sampled_contact_stationarity", "solve_sampled_contact",
    "V2_UNILATERAL_CONTACT_VERSION", "UnilateralConstraint", "UnilateralContactResult",
    "solve_unilateral_contact", "V2_PRODUCTION_VERSION", "V2_ACCEPTED_FEATURES",
    "solve_v2", "v2_backend_status", "clear_v2_production_caches",
    "v2_production_cache_stats",
)
