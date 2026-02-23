from dataclasses import dataclass
from ..attachment import Attachment

@dataclass
class FiberVCP:
    fiber_id: str
    origin: Attachment
    insertion: Attachment
    resolution: int = 16
    thickness: float = 0.01
