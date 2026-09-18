"""Blender port for live, targeted profile operations and native receipt markers."""
from contextlib import contextmanager
from ...app.use_cases import muscle_profile as commands
from ...app.use_cases.fiber_surface_create import create_native_muscle
from ...core.authoring.codec import encode, decode

MARKERS = {"muscle_profile_configure.v1": "af_authoring_profile_receipt", "muscle_from_surface.v1": "af_authoring_muscle_creation"}


def inspect(port, target):
    return commands.inspect(port.root, port.scene, target.get("muscle_id", ""), target.get("fiber_surface_id", ""))[1]


def preview(port, target, configuration):
    captured, state = commands.inspect(port.root, port.scene, target.get("muscle_id", ""), target.get("fiber_surface_id", ""))
    normalized, _, batch = commands.preview(captured, configuration)
    result = batch.results[0]
    geometry = dict(base=result.base_vertices.tolist(), inflated=result.inflated_vertices.tolist(), faces=result.faces.tolist())
    metadata = dict(rows=result.row_count, columns=result.column_count, vertices=len(result.base_vertices),
                    backend=batch.backend, numeric_ms=batch.elapsed_ms, mathematical_validity="valid")
    return dict(state, configuration=normalized, evaluation=metadata), geometry


@contextmanager
def mutation(port, target, configuration=None, create=False, name=""):
    captured, _ = commands.inspect(port.root, port.scene, target.get("muscle_id", ""), target.get("fiber_surface_id", ""))
    with commands.transaction(port.root, port.scene, captured.muscle):
        if create:
            muscle = create_native_muscle(port.root, port.scene, captured.source.id, name, configuration)
        else:
            muscle = captured.muscle
            commands.configure(port.root, port.scene, muscle.id, configuration)
        yield muscle.id


def marker(port, muscle_id, kind, receipt=None):
    muscle = next((item for item in port.root.af_vcp_system.muscles if item.id == muscle_id), None)
    if muscle is None:
        return None
    key = MARKERS[kind]
    if receipt is not None:
        muscle[key] = encode(receipt)
    raw = muscle.get(key)
    return decode(raw) if raw else None


def recover_marker(port, request_id, kind):
    kinds = (kind,) if kind else MARKERS
    records = [marker(port, item.id, key) for item in port.root.af_vcp_system.muscles for key in kinds]
    matches = [row for row in records if row and row.get("request_id") == request_id]
    if len(matches) > 1:
        raise ValueError("PROFILE_RECEIPT_AMBIGUOUS")
    return matches[0] if matches else None
