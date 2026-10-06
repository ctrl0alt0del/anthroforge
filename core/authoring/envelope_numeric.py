"""Portable envelope configurations lowered into the canonical numeric request."""
from dataclasses import replace
from types import SimpleNamespace
from .envelope_config import normalize, side_values
from ..vcp.muscle_envelope import MuscleEnvelopeSpec


def configured(request, value, part_ids=('main',)):
    value = normalize(value); records = {p['part_id']: p for p in value['parts']}
    if set(records) != set(part_ids): raise ValueError('ENVELOPE_PART_MISMATCH')
    old = request.part_specs if hasattr(request, 'assembly') else (request.spec,)
    a = tuple(numeric_spec(spec, records[key]['a']) for spec, key in zip(old, part_ids))
    b = tuple(numeric_spec(spec, records[key]['b']) for spec, key in zip(old, part_ids))
    request = replace(request, part_specs=a) if hasattr(request, 'assembly') else replace(request, spec=a[0])
    env = MuscleEnvelopeSpec(b, value['enabled'], value['reverse_sides'])
    return one_side(request, env) if value['sides'] == 'one' else replace(request, envelope=env)


def numeric_spec(spec, side):
    from ..vcp.height_smoothing import capture
    from ..vcp.muscle_section_profile import profile_from_muscle
    values = side_values(side); updates = {k: v for k, v in values.items() if k in spec.__dataclass_fields__}
    updates['smoothing'] = capture(SimpleNamespace(**values))
    if 'inflation_ctrl_world' in values: updates['control_world'] = tuple(values['inflation_ctrl_world'])
    if side['mode'] == 'section_profile': updates['section_profile'] = profile_from_muscle(SimpleNamespace(**values))
    else: updates['initialize_control'] = not values.get('inflation_ctrl_initialized', False)
    return replace(spec, **updates)


def one_side(request, env):
    if hasattr(request, 'assembly'):
        return replace(request, envelope=None, assembly=replace(request.assembly, flip=request.assembly.flip ^ env.reverse),
                       part_specs=tuple(replace(s, inflation_enabled=s.inflation_enabled and env.enabled) for s in request.part_specs))
    return replace(request, envelope=None, spec=replace(request.spec, flip_normals=request.spec.flip_normals ^ env.reverse,
                   inflation_enabled=request.spec.inflation_enabled and env.enabled))


def evaluate_output(output, envelope, request):
    from ..vcp.muscle_numeric import execute_muscle_batch
    from ..vcp.muscle_envelope import geometry
    ids = ('main', *(b.connection.id for b in request.assembly.branches)) if hasattr(request, 'assembly') else ('main',)
    result = execute_muscle_batch((configured(request, envelope, ids),)).results[0]
    if result.error: raise ValueError(result.error)
    output.update(geometry(result), envelope_configuration=normalize(envelope))
    return output


def measurements(output):
    import numpy as np
    from .metrics import sections
    from ..vcp.muscle_envelope_native import diagnostics
    rows = sections(output)
    spans = [row['max_material_span'] if 'side_a' in output else row['height'] for row in rows]
    area = diagnostics(output['inflated'], output.get('inflated_faces', output['faces']))['surface_area']
    return dict(height=max(spans), width=max(row['width'] for row in rows),
                belly_position=rows[int(np.argmax(spans))]['s'], area=area)
