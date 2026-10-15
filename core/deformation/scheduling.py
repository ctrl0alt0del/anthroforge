"""Per-root debounce/coalescing state; callers own Blender access and workers."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Revision:
    epoch: str
    reference: str
    settings: str
    anatomy: str


@dataclass
class Slot:
    pending: Revision | None = None
    running: Revision | None = None
    due: float = 0.0
    cancel: object = None
    cancellation_requested: bool = False


class UpdateQueue:
    def __init__(self, debounce=0.3):
        self.debounce = debounce
        self.slots = {}

    def enqueue(self, root_id, revision, now):
        slot = self.slots.setdefault(root_id, Slot())
        slot.pending = revision; slot.due = now+self.debounce
        if slot.running is not None and slot.running != revision and not slot.cancellation_requested:
            if slot.cancel is not None: slot.cancel()
            slot.cancellation_requested = True

    def ready(self, now):
        return tuple(key for key, slot in self.slots.items()
                     if slot.pending is not None and slot.running is None and now >= slot.due)

    def start(self, root_id, cancel, now):
        if root_id not in self.ready(now):
            raise RuntimeError("Deformation update is not ready or already running.")
        slot = self.slots[root_id]; slot.running = slot.pending; slot.pending = None
        slot.cancel = cancel; slot.cancellation_requested = False
        return slot.running

    def finish(self, root_id, revision, current):
        slot = self.slots.get(root_id)
        if slot is None or slot.running != revision: return False
        accepted = revision == current and not slot.cancellation_requested
        slot.running = None; slot.cancel = None; slot.cancellation_requested = False
        if slot.pending == revision and accepted: slot.pending = None
        if slot.pending is None: self.slots.pop(root_id, None)
        return accepted

    def cancel(self, root_id):
        slot = self.slots.get(root_id)
        if slot is None: return
        slot.pending = None
        if slot.running is None: self.slots.pop(root_id, None); return
        if slot.cancel is not None and not slot.cancellation_requested: slot.cancel()
        slot.cancellation_requested = True

    def reset(self):
        for root_id in tuple(self.slots): self.cancel(root_id)
        self.slots.clear()
