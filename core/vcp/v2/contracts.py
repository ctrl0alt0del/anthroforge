"""Immutable, serializable, Blender-independent Fiber V2 contracts."""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from math import isfinite


V2_CONTRACT_VERSION = 1
V2_ENGINE_VERSION = "fiber-v2-contract-1"


class V2Quality(str, Enum):
    INTERACTIVE = "INTERACTIVE"
    FINAL = "FINAL"


class V2Topology(str, Enum):
    OPEN = "OPEN"
    CYCLIC = "CYCLIC"


class V2AnchorRole(str, Enum):
    ENDPOINT_A = "ENDPOINT_A"
    TOUCH = "TOUCH"
    ENDPOINT_B = "ENDPOINT_B"
    LOOP = "LOOP"


class V2Termination(str, Enum):
    CONVERGED = "CONVERGED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    STALLED = "STALLED"
    BLOCKED = "BLOCKED"
    NO_FEASIBLE_PATH = "NO_FEASIBLE_PATH"
    UNSAFE_OUTPUT = "UNSAFE_OUTPUT"
    INVALID_ATTACHMENT = "INVALID_ATTACHMENT"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"


def _enum(enum_type, value):
    return value if isinstance(value, enum_type) else enum_type(value)


def _finite_float(value, name, minimum=None):
    result = float(value)
    if not isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} is outside its valid range")
    return result


def _positive_int(value, name):
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _vec3(value, name="point"):
    result = tuple(_finite_float(item, name) for item in tuple(value or ()))
    if len(result) != 3:
        raise ValueError(f"{name} must contain three coordinates")
    return result


def _points(value, name="points"):
    return tuple(_vec3(item, name) for item in tuple(value or ()))


def _triangle(value):
    result = tuple(int(item) for item in tuple(value or ()))
    if len(result) != 3 or any(item < 0 for item in result):
        raise ValueError("triangle indices must be three nonnegative integers")
    return result


def _triangles(value):
    return tuple(_triangle(item) for item in tuple(value or ()))


def _tokens(value):
    return tuple(str(item) for item in tuple(value or ()))


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def encode_contract(value):
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_contract_signature(value):
    return sha256(encode_contract(value).encode("utf-8")).hexdigest()


def _payload(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("contract payload must be a JSON object")
    return dict(value)


@dataclass(frozen=True)
class V2Settings:
    topology: V2Topology = V2Topology.OPEN
    quality: V2Quality = V2Quality.INTERACTIVE
    node_count: int = 64
    max_accepted_steps: int = 24
    length_weight: float = 0.9
    curvature_weight: float = 0.02
    fidelity_weight: float = 1.0

    def __post_init__(self):
        object.__setattr__(self, "topology", _enum(V2Topology, self.topology))
        object.__setattr__(self, "quality", _enum(V2Quality, self.quality))
        object.__setattr__(self, "node_count", _positive_int(self.node_count, "node_count"))
        object.__setattr__(self, "max_accepted_steps", _positive_int(self.max_accepted_steps, "max_accepted_steps"))
        _set_weights(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_payload(value))


def _set_weights(settings):
    names = ("length_weight", "curvature_weight", "fidelity_weight")
    for name in names:
        minimum = 1.0e-300 if name == "fidelity_weight" else 0.0
        object.__setattr__(settings, name, _finite_float(getattr(settings, name), name, minimum))


@dataclass(frozen=True)
class V2ResolvedTolerances:
    length_scale: float = 1.0
    coordinate_scale: float = 1.0
    numeric_floor: float = 1.0e-9
    clearance_slack: float = 1.0e-9
    pin_tolerance: float = 1.0e-6
    fixed_point_tolerance: float = 1.0e-4
    stationarity_tolerance: float = 1.0e-4
    relative_energy_tolerance: float = 1.0e-5

    def __post_init__(self):
        for name in _tolerance_names():
            object.__setattr__(self, name, _finite_float(getattr(self, name), name, 0.0))
        if self.length_scale <= 0.0 or self.coordinate_scale <= 0.0:
            raise ValueError("resolved scales must be positive")

    @classmethod
    def from_payload(cls, value):
        return cls(**_payload(value))


def _tolerance_names():
    return tuple(item.name for item in fields(V2ResolvedTolerances))


@dataclass(frozen=True)
class V2CollisionPolicy:
    collision_radius: float = 0.002
    owner_contact_mode: str = "AUTHORED_LOCAL"
    require_ccd: bool = True
    require_static_validation: bool = True
    backend_name: str = "af_fiber_ccd"
    backend_version: str = ""

    def __post_init__(self):
        object.__setattr__(self, "collision_radius", _finite_float(self.collision_radius, "collision_radius", 0.0))
        object.__setattr__(self, "owner_contact_mode", str(self.owner_contact_mode or ""))
        object.__setattr__(self, "backend_name", str(self.backend_name or ""))
        object.__setattr__(self, "backend_version", str(self.backend_version or ""))
        if not self.owner_contact_mode:
            raise ValueError("owner_contact_mode is required")

    @classmethod
    def from_payload(cls, value):
        return cls(**_payload(value))


@dataclass(frozen=True)
class V2Anchor:
    point: tuple
    owner_id: str = ""
    role: V2AnchorRole = V2AnchorRole.TOUCH
    authored_index: int = 0

    def __post_init__(self):
        object.__setattr__(self, "point", _vec3(self.point, "anchor point"))
        object.__setattr__(self, "owner_id", str(self.owner_id or ""))
        object.__setattr__(self, "role", _enum(V2AnchorRole, self.role))
        object.__setattr__(self, "authored_index", int(self.authored_index))
        if self.authored_index < 0:
            raise ValueError("authored_index must be nonnegative")

    @classmethod
    def from_payload(cls, value):
        return cls(**_payload(value))


@dataclass(frozen=True)
class V2ColliderSnapshot:
    collider_id: str
    owner_id: str
    vertices: tuple
    triangles: tuple
    generation: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "collider_id", str(self.collider_id or ""))
        object.__setattr__(self, "owner_id", str(self.owner_id or ""))
        object.__setattr__(self, "vertices", _points(self.vertices, "collider vertex"))
        object.__setattr__(self, "triangles", _triangles(self.triangles))
        object.__setattr__(self, "generation", _tokens(self.generation))
        _validate_triangle_bounds(self)

    @classmethod
    def from_payload(cls, value):
        return cls(**_payload(value))


def _validate_triangle_bounds(collider):
    if not collider.collider_id:
        raise ValueError("collider_id is required")
    limit = len(collider.vertices)
    if any(index >= limit for triangle in collider.triangles for index in triangle):
        raise ValueError("triangle index exceeds collider vertex count")


@dataclass(frozen=True)
class V2Diagnostics:
    structural_energy: float = 0.0
    length_energy: float = 0.0
    curvature_energy: float = 0.0
    contact_energy: float = 0.0
    fixed_point_residual: float = 0.0
    stationarity_residual: float = 0.0
    node_clearance_residual: float = 0.0
    edge_clearance_residual: float = 0.0
    ccd_step_fraction: float = 1.0
    ccd_candidate_pairs: int = 0
    ccd_tested_pairs: int = 0
    accepted_steps: int = 0
    rejected_steps: int = 0
    accelerated_steps: int = 0

    def __post_init__(self):
        _set_diagnostic_floats(self)
        _set_diagnostic_counts(self)
        if self.ccd_step_fraction > 1.0:
            raise ValueError("ccd_step_fraction must not exceed one")

    @classmethod
    def from_payload(cls, value):
        return cls(**_payload(value))


def _set_diagnostic_floats(diagnostics):
    names = tuple(item.name for item in fields(V2Diagnostics) if item.type is float)
    for name in names:
        value = _finite_float(getattr(diagnostics, name), name, 0.0)
        object.__setattr__(diagnostics, name, value)


def _set_diagnostic_counts(diagnostics):
    names = tuple(item.name for item in fields(V2Diagnostics) if item.type is int)
    for name in names:
        value = int(getattr(diagnostics, name))
        if value < 0:
            raise ValueError(f"{name} must be nonnegative")
        object.__setattr__(diagnostics, name, value)


@dataclass(frozen=True)
class V2Request:
    token: int
    scene_id: str
    root_id: str
    source_revision: str
    settings: V2Settings
    tolerances: V2ResolvedTolerances
    collision_policy: V2CollisionPolicy
    anchors: tuple
    colliders: tuple
    symmetry_mode: str = "NONE"
    symmetry_axis: tuple = (1.0, 0.0, 0.0)
    symmetry_origin: tuple = (0.0, 0.0, 0.0)
    warm_seed: tuple = ()
    contract_version: int = V2_CONTRACT_VERSION
    engine_version: str = V2_ENGINE_VERSION

    def __post_init__(self):
        _set_request_identity(self)
        _set_request_data(self)
        if self.contract_version != V2_CONTRACT_VERSION:
            raise ValueError("unsupported V2 contract version")

    def signature_payload(self):
        payload = _plain(self)
        payload.pop("token", None)
        payload.pop("warm_seed", None)
        return payload

    def signature(self):
        cached = getattr(self, "_signature_cache", "")
        if cached:
            return cached
        value = stable_contract_signature(self.signature_payload())
        object.__setattr__(self, "_signature_cache", value)
        return value

    @classmethod
    def from_payload(cls, value):
        return _request_from_payload(_payload(value))


def _set_request_identity(request):
    object.__setattr__(request, "token", _positive_int(request.token, "token"))
    for name in ("scene_id", "root_id", "source_revision", "symmetry_mode", "engine_version"):
        object.__setattr__(request, name, str(getattr(request, name) or ""))
    object.__setattr__(request, "contract_version", int(request.contract_version))


def _set_request_data(request):
    object.__setattr__(request, "anchors", tuple(request.anchors or ()))
    object.__setattr__(request, "colliders", tuple(request.colliders or ()))
    object.__setattr__(request, "symmetry_axis", _vec3(request.symmetry_axis, "symmetry_axis"))
    object.__setattr__(request, "symmetry_origin", _vec3(request.symmetry_origin, "symmetry_origin"))
    object.__setattr__(request, "warm_seed", _points(request.warm_seed, "warm seed"))
    _validate_request_data(request)


def _validate_request_data(request):
    if not request.scene_id or not request.root_id or not request.source_revision:
        raise ValueError("scene, root, and source revision identities are required")
    if not request.engine_version:
        raise ValueError("engine_version is required")
    _validate_request_records(request)


def _validate_request_records(request):
    records = ((request.settings, V2Settings), (request.tolerances, V2ResolvedTolerances),
               (request.collision_policy, V2CollisionPolicy))
    if not all(isinstance(value, expected) for value, expected in records):
        raise ValueError("request settings, tolerances, and collision policy must use V2 contracts")
    if not all(isinstance(item, V2Anchor) for item in request.anchors):
        raise ValueError("anchors must contain V2Anchor values")
    if not all(isinstance(item, V2ColliderSnapshot) for item in request.colliders):
        raise ValueError("colliders must contain V2ColliderSnapshot values")


def _request_from_payload(payload):
    data = dict(payload)
    data["settings"] = V2Settings.from_payload(data["settings"])
    data["tolerances"] = V2ResolvedTolerances.from_payload(data["tolerances"])
    data["collision_policy"] = V2CollisionPolicy.from_payload(data["collision_policy"])
    data["anchors"] = tuple(V2Anchor.from_payload(item) for item in data.get("anchors", ()))
    data["colliders"] = tuple(V2ColliderSnapshot.from_payload(item) for item in data.get("colliders", ()))
    return V2Request(**data)


@dataclass(frozen=True)
class V2Result:
    request_signature: str
    termination: V2Termination
    points: tuple
    diagnostics: V2Diagnostics
    validated: bool = False
    route_branch: str = ""
    message: str = ""
    engine_version: str = V2_ENGINE_VERSION
    backend_version: str = ""
    contract_version: int = V2_CONTRACT_VERSION

    def __post_init__(self):
        _set_result_values(self)
        if self.contract_version != V2_CONTRACT_VERSION:
            raise ValueError("unsupported V2 contract version")

    @property
    def successful(self):
        return self.validated and self.termination is V2Termination.CONVERGED

    @classmethod
    def from_payload(cls, value):
        return _result_from_payload(_payload(value))


def _set_result_values(result):
    for name in ("request_signature", "route_branch", "message", "engine_version", "backend_version"):
        object.__setattr__(result, name, str(getattr(result, name) or ""))
    object.__setattr__(result, "termination", _enum(V2Termination, result.termination))
    object.__setattr__(result, "points", _points(result.points))
    object.__setattr__(result, "validated", bool(result.validated))
    object.__setattr__(result, "contract_version", int(result.contract_version))
    _validate_result_values(result)


def _validate_result_values(result):
    if not result.request_signature or not result.engine_version:
        raise ValueError("result request signature and engine version are required")
    if not isinstance(result.diagnostics, V2Diagnostics):
        raise ValueError("result diagnostics must use V2Diagnostics")


def _result_from_payload(payload):
    data = dict(payload)
    data["diagnostics"] = V2Diagnostics.from_payload(data["diagnostics"])
    return V2Result(**data)


def decode_request(value):
    return V2Request.from_payload(value)


def decode_result(value):
    return V2Result.from_payload(value)
