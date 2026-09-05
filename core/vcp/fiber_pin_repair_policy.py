"""Pure records and decision policy for Fiber pin repair."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FiberPinRef:
    fiber_id: str
    role: str
    index: int
    owner: str
    raw: str
    point: tuple
    offset: float
    radius: float
    blocker: str
    relation: str


@dataclass(frozen=True)
class FiberPinCandidate:
    owner: str
    raw: str
    point: tuple
    displacement: float


@dataclass(frozen=True)
class FiberPinRepair:
    pin: FiberPinRef
    candidate: FiberPinCandidate
    reason: str
    risky: bool


@dataclass(frozen=True)
class FiberPinFailure:
    pin: FiberPinRef
    reason: str


@dataclass(frozen=True)
class FiberPinRepairPlan:
    signature: tuple
    fiber_ids: tuple
    repairs: tuple
    failures: tuple
    elapsed_ms: float

    @property
    def risky(self):
        return tuple(row for row in self.repairs if row.risky)


@dataclass(frozen=True)
class FiberPinRepairReport:
    repaired_pins: int
    repaired_fibers: int
    unresolved_pins: int
    failed_fibers: tuple
    committed_fibers: tuple


def serialization_guard(radius):
    return max(1.0e-6, 1.0e-3 * float(radius))


def auto_repair_search_distance(radius):
    return max(5.0 * float(radius), 8.0 * serialization_guard(radius), 1.0e-5)


def use_owner_transfer(pin, current, alternate):
    if pin.relation != "UNRELATED" or not alternate: return False
    if current.displacement <= 5.0 * pin.radius: return False
    return alternate.displacement <= 3.0 * pin.radius and alternate.displacement <= 0.5 * current.displacement
