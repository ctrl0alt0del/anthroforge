from dataclasses import dataclass


@dataclass
class DeformerRuntimeStep:
    deformer: object
    deformer_state: object


class DeformerPipeline:
    def __init__(self, shape, shape_state):
        self.shape = shape
        self.shape_state = shape_state
        self._steps = self._build_steps()
        self._prepare_step_runtime_context()

    def _build_steps(self):
        state_by_id = {}
        for ds in list(getattr(self.shape_state, "deformers", []) or []):
            state_by_id[str(getattr(ds, "deformer_id", "") or "")] = ds

        out = []
        for d in list(self.shape.get_deformers() or []):
            did = str(getattr(d, "deformer_id", d.__class__.__name__.lower()) or "")
            ds = state_by_id.get(did, None)
            if ds is None:
                continue
            if not bool(getattr(ds, "enabled", True)):
                continue
            out.append(DeformerRuntimeStep(deformer=d, deformer_state=ds))
        return out

    def _prepare_step_runtime_context(self):
        raw_domain = list(getattr(self.shape, "deformer_domain_points", lambda: [])() or [])
        domain = [p.copy() for p in raw_domain]
        if not domain:
            return
        for step in self._steps:
            step.deformer.prepare_state_from_domain(self.shape, step.deformer_state, domain)
            domain = [step.deformer.forward_state(p.copy(), self.shape, step.deformer_state) for p in domain]

    def forward_point(self, local_point):
        spaces = self.evaluate_spaces(local_point)
        return spaces["FINAL"].copy()

    def inverse_point(self, deformed_local_point):
        return self.inverse_point_from_space(deformed_local_point, "FINAL")

    def evaluate_spaces(self, local_point):
        p = local_point.copy()
        out = {"BASE": p.copy()}
        for step in self._steps:
            p = step.deformer.forward_state(p, self.shape, step.deformer_state)
            sid = str(getattr(step.deformer_state, "deformer_id", "") or "")
            out[f"AFTER_{sid}"] = p.copy()
        out["FINAL"] = p.copy()
        return out

    def sample_point_in_space(self, local_point, space="FINAL"):
        spaces = self.evaluate_spaces(local_point)
        key = str(space or "FINAL").upper()
        return spaces.get(key, spaces["FINAL"]).copy()

    def inverse_point_from_space(self, point_in_space, space="FINAL"):
        key = str(space or "FINAL").upper()
        if key == "BASE":
            return point_in_space.copy()

        p = point_in_space.copy()
        if key == "FINAL":
            for step in reversed(self._steps):
                p = step.deformer.inverse_state(p, self.shape, step.deformer_state)
            return p

        if key.startswith("AFTER_"):
            did = key[len("AFTER_") :]
            idx = -1
            for i, step in enumerate(self._steps):
                if str(getattr(step.deformer_state, "deformer_id", "") or "").upper() == did:
                    idx = i
                    break
            if idx < 0:
                return self.inverse_point_from_space(point_in_space, "FINAL")
            for step in reversed(self._steps[: idx + 1]):
                p = step.deformer.inverse_state(p, self.shape, step.deformer_state)
            return p

        return self.inverse_point_from_space(point_in_space, "FINAL")

    def forward_geometry(self, verts, faces):
        out_verts = [v.copy() for v in list(verts or [])]
        out_faces = list(faces or [])
        for step in self._steps:
            out_verts, out_faces = step.deformer.apply_geometry_state(
                out_verts,
                out_faces,
                self.shape,
                step.deformer_state,
            )
        return out_verts, out_faces
