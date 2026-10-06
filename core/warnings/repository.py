"""Single authoritative warning store; successful reconciliation is scope-atomic."""
from collections import defaultdict
from contextlib import contextmanager
import logging


class WarningRepository:
    def __init__(self):
        self.revision = 0
        self.records, self.scopes, self.states, self.metadata = {}, {}, {}, {}
        self.provider_states = {}
        self.index, self.listeners = defaultdict(set), []
        self.discovery = "UNSCANNED"
        self._batch_depth, self._notification_pending = 0, False

    def subscribe(self, callback):
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback) if callback in self.listeners else None

    def changed(self):
        self.revision += 1
        self._notification_pending = True
        if not self._batch_depth: self._notify()

    def _notify(self):
        self._notification_pending = False
        for listener in tuple(self.listeners):
            try:
                listener(self)
            except Exception:
                logging.getLogger(__name__).exception("Warning projection failed")

    @contextmanager
    def batch(self):
        self._batch_depth += 1
        try: yield self
        finally:
            self._batch_depth -= 1
            if not self._batch_depth and self._notification_pending: self._notify()

    def clear(self, state="UNSCANNED"):
        self.records.clear(); self.scopes.clear(); self.states.clear(); self.metadata.clear()
        self.provider_states.clear()
        self.index.clear(); self.discovery = state
        self.changed()

    def state(self, scope, status, generation=0, error="", provider="fiber_hard_anchor.v1"):
        value = dict(status=status, generation=generation, error=str(error))
        if self.provider_states.get((scope, provider)) != value:
            self._state(scope, provider, value)
            self.changed()

    def _state(self, scope, provider, value):
        self.provider_states[scope, provider] = value
        values = [state for (key, _provider), state in self.provider_states.items() if key == scope]
        order = ("FAILED", "CANCELLED", "CHECKING", "PENDING", "UNSCANNED", "COMPLETE")
        self.states[scope] = min(values, key=lambda state: order.index(state["status"]))

    def replace(self, scope, records, generation=0, metadata=None, provider="fiber_hard_anchor.v1"):
        rows = {row.id: row for row in records}
        if any(row.entity.scope != scope or row.provider != provider for row in rows.values()):
            raise ValueError("Cannot reconcile a different entity scope")
        self._remove_rows(scope, provider)
        self.records.update(rows); self.scopes.setdefault(scope, set()).update(rows)
        for row in rows.values():
            self._index(row)
        self.metadata[scope, provider] = metadata
        self._state(scope, provider, dict(status="COMPLETE", generation=generation, error=""))
        self.changed()

    def _index(self, row):
        for key, value in fields(row).items():
            self.index[(key, value)].add(row.id)

    def _remove_rows(self, scope, provider=None):
        identities = self.scopes.get(scope, set())
        selected = tuple(key for key in identities if provider is None or self.records[key].provider == provider)
        for identity in selected:
            row = self.records.pop(identity)
            identities.discard(identity)
            for key, value in fields(row).items():
                bucket = self.index[(key, value)]
                bucket.discard(identity)
                if not bucket:
                    self.index.pop((key, value))
        if not identities:
            self.scopes.pop(scope, None)

    def upsert(self, row):
        existing = [self.records[key] for key in self.scopes.get(row.entity.scope, ())
                    if self.records[key].provider == row.provider and key != row.id]
        self.replace(row.entity.scope, (*existing, row), row.source_generation, provider=row.provider)

    def remove(self, scope):
        self._remove_rows(scope)
        self.states.pop(scope, None)
        for key in tuple(self.provider_states):
            if key[0] == scope:
                self.provider_states.pop(key); self.metadata.pop(key, None)
        self.changed()

    def query(self, filters=None, offset=0, limit=100):
        selected = set(self.records)
        for key, value in (filters or {}).items():
            if value is not None and key in FILTERS:
                selected.intersection_update(self.index.get((key, str(value)), ()))
        rows = sorted((self.records[key] for key in selected), key=sort_key)
        start, count = max(0, int(offset)), min(200, max(0, int(limit)))
        return len(rows), tuple(rows[start:start + count])

    def status(self, filters=None):
        values = [value for scope, value in self.states.items() if scope_matches(scope, filters)]
        counts = {state: sum(v["status"] == state for v in values) for state in STATES}
        complete = self.discovery == "COMPLETE" and all(v["status"] == "COMPLETE" for v in values)
        return dict(complete=complete, discovery=self.discovery, counts=counts,
                    failures=[dict(scope=scope, **v) for scope, v in self.states.items()
                              if v["status"] == "FAILED" and scope_matches(scope, filters)])


STATES = ("UNSCANNED", "PENDING", "CHECKING", "COMPLETE", "FAILED", "CANCELLED")
FILTERS = ("scene", "root", "entity", "kind", "code", "type", "authoring_id")


def fields(row):
    ref = row.entity
    return dict(scene=ref.scene, root=ref.root, entity=ref.native_id, kind=ref.kind,
                code=row.code, type=row.code, authoring_id=ref.authoring_id)


def sort_key(row):
    pin = row.pin
    return (row.entity.scope, row.code, "" if pin is None else pin.role,
            -1 if pin is None else pin.index, row.id)


def scope_matches(scope, filters):
    """Include ancestor check coverage even before a filtered entity is discovered."""
    values = dict(scene=scope[1], root=scope[2], kind=scope[3], entity=scope[4])
    keys = {"FILE": (), "SCENE": ("scene",), "ROOT": ("scene", "root")}.get(scope[3], tuple(values))
    return all(str(value) == values[key] for key, value in (filters or {}).items()
               if key in keys and value is not None)
