"""Native envelope scene port; transactions include the authoring journal write."""
from contextlib import contextmanager
from ...app.use_cases import muscle_envelope as commands
from ...core.vcp.muscle_envelope import geometry


def inspect(port, target):
    return commands.inspect(port.root, port.scene, target['muscle_id'])[1]


def preview(port, target, configuration):
    captured, state = commands.inspect(port.root, port.scene, target['muscle_id'])
    normalized, _, batch = commands.preview(captured, configuration)
    result = batch.results[0]
    state.update(configuration=normalized, evaluation=dict(backend=batch.backend, numeric_ms=batch.elapsed_ms,
        base_vertices=len(result.base_vertices), output_vertices=len(result.inflated_vertices)), diagnostics=result.diagnostics,
        diagnostics_scope="proposed_geometry")
    return state, geometry(result)


@contextmanager
def mutation(port, target, configuration):
    captured, _ = commands.inspect(port.root, port.scene, target['muscle_id'])
    with commands.transaction(port.root, port.scene, captured.muscle):
        commands.configure(port.root, port.scene, captured.muscle.id, configuration)
        yield captured.muscle.id
