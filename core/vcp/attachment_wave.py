"""Immutable pure-data contracts for dependency-wave attachment propagation."""

from dataclasses import dataclass
from enum import Enum

import numpy as np


ATTACHMENT_WAVE_VERSION = "attachment-wave-3"


class AttachmentExecutorKind(str, Enum):
    NATIVE_WAVE = "NATIVE_WAVE"
    SERIAL_REFERENCE = "SERIAL_REFERENCE"


@dataclass(frozen=True)
class AttachmentSurfaceSnapshot:
    target_id: str
    owner_index: int
    vertices: np.ndarray
    triangles: np.ndarray
    relative_matrix: np.ndarray
    relative_rotation: np.ndarray
    generation: tuple = ()


@dataclass(frozen=True)
class SCPAttachmentOperation:
    child_id: str
    parent_id: str
    child_index: int
    parent_index: int
    surface_index: int
    depth: int
    triangle: tuple
    weights: tuple
    flow_triangle: tuple
    flow_weights: tuple
    tangent_mode: int
    follow_rotation: bool
    tangent_hint: tuple
    parent_offset: tuple
    child_origin: tuple
    child_tangent: tuple
    child_normal: tuple
    child_scale: tuple
    backsolve: bool = False
    back_parent_index: int = -1
    back_parent_local: tuple = (0.0, 0.0, 0.0)
    back_anchor_local: tuple = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class FiberNodeAttachmentOperation:
    fiber_id: str
    node_index: int
    owner_index: int
    surface_index: int
    triangle: tuple
    weights: tuple
    offset: tuple
    influence_weight: float = 1.0


@dataclass(frozen=True)
class AttachmentPropagationRequest:
    token: int
    scene_id: int
    root_id: int
    scp_ids: tuple
    matrices: np.ndarray
    rotations: np.ndarray
    initial_scp_status: tuple
    surfaces: tuple
    scp_operations: tuple
    waves: tuple
    fiber_ids: tuple
    fiber_counts: tuple
    fiber_operations: tuple
    generations: tuple = ()


@dataclass(frozen=True)
class AttachmentPropagationResult:
    matrices: np.ndarray
    rotations: np.ndarray
    scp_status: tuple
    fiber_points: tuple
    fiber_status: tuple
    telemetry: tuple = ()
    fallback_reason: str = ""


def readonly_array(values, width):
    array = np.ascontiguousarray(values, dtype=np.float64).reshape((-1, width))
    array.flags.writeable = False
    return array


def request_cost(request):
    return 16 * len(request.scp_operations) + len(request.fiber_operations)
