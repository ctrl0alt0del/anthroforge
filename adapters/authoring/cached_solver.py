"""Only independently accepted native paths enter the content-addressed cache."""
from dataclasses import asdict
import numpy as np
from ...core.authoring.codec import digest
from ...core.vcp.v3.production import V3_PRODUCTION_VERSION


class CachedFiberSolver:
    def __init__(self, solver, store):
        self.solver, self.store = solver, store
        self.snapshot, self.geometry_key = None, None
        self.solved, self.hits = 0, 0

    def solve(self, plan, snapshot, budget_ms):
        if snapshot is not self.snapshot:
            self.snapshot, self.geometry_key = snapshot, geometry_digest(snapshot)
        key = [V3_PRODUCTION_VERSION, "material-nodes-3", self.geometry_key, asdict(plan)]
        cached = self.store.get("fibers", key)
        if cached is not None:
            self.hits += 1
            return np.array(cached[0]), np.array(cached[1]), cached[2]
        points, samples, termination = self.solver.solve(plan, snapshot, budget_ms)
        self.solved += 1
        self.store.put("fibers", key, [points.tolist(), samples.tolist(), termination])
        return points, samples, termination


def geometry_digest(snapshot):
    return digest([(m.id, m.vertices.tolist(), m.triangles.tolist(), m.matrix.tolist()) for m in snapshot.meshes])
