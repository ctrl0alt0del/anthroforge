from dataclasses import dataclass


PHASE_INPUT = "INPUT"
PHASE_LOCAL_EVAL = "LOCAL_EVAL"
PHASE_ATTACHMENT_WORLD = "ATTACHMENT_WORLD"
PHASE_PROBES = "PROBES"
PHASE_CONSTRAINT_APPLY = "CONSTRAINT_APPLY"
PHASE_VIS_SYNC = "VIS_SYNC"

PHASE_ORDER = (
    PHASE_INPUT,
    PHASE_LOCAL_EVAL,
    PHASE_ATTACHMENT_WORLD,
    PHASE_PROBES,
    PHASE_CONSTRAINT_APPLY,
    PHASE_VIS_SYNC,
)

MUT_INPUT = "INPUT"
MUT_DERIVED = "DERIVED"
MUT_PROBE = "PROBE"

EDGE_EVAL = "EVAL"
EDGE_ATTACHMENT = "ATTACHMENT"
EDGE_CONSTRAINT_READ = "CONSTRAINT_READ"
EDGE_CONSTRAINT_WRITE = "CONSTRAINT_WRITE"


@dataclass(frozen=True, order=True)
class PortRef:
    entity_type: str
    entity_id: str
    port_key: str
    phase: str
    mutability: str


@dataclass(frozen=True)
class Edge:
    src: PortRef
    dst: PortRef
    edge_type: str

