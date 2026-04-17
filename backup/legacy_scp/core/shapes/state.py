from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DeformerState:
    deformer_id: str
    enabled: bool = True
    order: int = 100
    params: Dict[str, object] = field(default_factory=dict)
    version: int = 0


@dataclass
class ShapeState:
    shape_type: str
    base_data: Dict[str, object] = field(default_factory=dict)
    deformers: List[DeformerState] = field(default_factory=list)
    version: int = 0


@dataclass(frozen=True)
class ControlBinding:
    kind: str  # PARAM | GEOMETRY_SAMPLE | FRAME_SAMPLE
    space: str  # BASE | AFTER_<deformer_id> | FINAL
    target_path: str
    metadata: Optional[Dict[str, object]] = None

