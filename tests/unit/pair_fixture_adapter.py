"""Synchronous test adapter; production execution stays asynchronous."""
from dataclasses import dataclass
from time import sleep, monotonic
import numpy as np
from core.muscle_pairs.native import NativePairEngine
from core.muscle_pairs.model import DomainKey, DetectionSettings, snapshot


@dataclass(frozen=True)
class Side:
    id: str
    family: str
    base: np.ndarray
    own: np.ndarray
    direction: np.ndarray
    faces: np.ndarray
    root: str = 'skeleton'
    instance: str = 'source'
    side: str = 'A'
    displacement: float = 0.
    enabled: bool = True


def domain(side):
    n = len(side.faces)
    return snapshot(DomainKey(side.root, side.id, side.instance, side.side), side.family, '',
        side.base, side.own, side.direction, side.faces, np.zeros(n, dtype=np.int64), np.arange(n), side.displacement, side.enabled)


def wait(engine):
    deadline = monotonic()+60
    while engine.poll().state < 2 and monotonic() < deadline: sleep(.001)
    report = engine.poll(); engine.release()
    if report.state != 2: raise ValueError('budget/native: '+report.message.decode())
    return engine.summary()


def materialize(engine, summary):
    records = []; raw_fragments, raw_points = [], []
    for row in summary['pairs']:
        raw = engine.footprint(row['index'], engine.generation); points = raw['point_array']
        for f in raw['fragment_array']:
            record = {k: f[k].item() for k in f.dtype.names}
            record.update(receiver_id=engine.domains[f['receiver']].key.muscle, provider_id=engine.domains[f['provider']].key.muscle)
            record['polygon'] = {k: points[k][f['start']:f['start']+f['count']].tolist() for k in points.dtype.names}
            records.append(record)
        raw_fragments.append(raw['fragment_array']); raw_points.append(points)
    return dict(stats=summary['timings'], pairs=summary['pairs'], fragments=records, activated_relations=[],
        fragment_array=np.concatenate(raw_fragments) if raw_fragments else [], point_array=np.concatenate(raw_points) if raw_points else [])


class PairDetector:
    def __init__(self, search_distance=.1, fragment_limit=2000000):
        self.engine = NativePairEngine(); self.domains = []; self.generation = 0
        self.settings = DetectionSettings(search_distance=search_distance, fragment_limit=fragment_limit)

    def add(self, side):
        value = domain(side)
        if not all(np.isfinite(v).all() for v in (value.base, value.own, value.direction)): raise ValueError('nonfinite')
        if not np.allclose(np.linalg.norm(value.direction, axis=1), 1, atol=1e-7): raise ValueError('direction')
        if value.faces.min() < 0 or value.faces.max() >= len(value.base): raise ValueError('index')
        self.domains.append(value)
        return len(self.domains)-1

    def detect(self, exhaustive=False, materialize=True):
        if self.engine.handle is None: raise ValueError('closed')
        self.generation += 1; self.engine.submit(self.domains, self.settings, self.generation, exhaustive)
        return globals()['materialize'](self.engine, wait(self.engine))

    def __enter__(self): return self

    def __exit__(self, *_): self.engine.close()
