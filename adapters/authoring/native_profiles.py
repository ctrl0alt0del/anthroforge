"""Blender port for live, targeted profile operations and native receipt markers."""
from contextlib import contextmanager
from ...app.use_cases import muscle_profile as commands
from ...app.use_cases.fiber_surface_create import create_native_muscle
from ...core.authoring.codec import encode, decode

MARKERS = {"muscle_profile_configure.v1": "af_authoring_profile_receipt", "muscle_from_surface.v1": "af_authoring_muscle_creation"}
MARKERS['muscle_inflation_configure.v1'] = 'af_authoring_envelope_receipt'
MARKERS['muscle_domain_configure.v1'] = 'af_authoring_domain_receipt'


def inspect(port, target):
    captured, state = commands.inspect(port.root, port.scene, target.get("muscle_id", ""), target.get("fiber_surface_id", ""))
    if getattr(captured.muscle, "envelope_sides", "") == "BOTH_SIDES":
        from ...core.authoring.codec import digest
        from ...core.authoring.envelope_config import configuration
        state.update(envelope_api_required=True, capability="muscle_inflation_envelope.v1",
                     envelope_configuration_revision=digest(configuration(port.root, captured.muscle)))
    return _smoothing_revision(port, captured.muscle, state)


def _smoothing_revision(port, muscle, state):
    from ...core.authoring.envelope_config import configuration
    from ...core.authoring.codec import digest
    if muscle is None: return state
    value = configuration(port.root, muscle)
    if any('smoothing' in part[side] for part in value['parts'] for side in ('a', 'b')):
        state['envelope_configuration_revision'] = digest(value)
    return state


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


@contextmanager
def domain_mutation(port, target, configuration):
    from ...app.use_cases import muscle_domain
    captured, _ = commands.inspect(port.root, port.scene, target['muscle_id'])
    with commands.transaction(port.root, port.scene, captured.muscle):
        muscle_domain.configure(port.root, port.scene, captured.muscle.id, configuration)
        yield captured.muscle.id


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
