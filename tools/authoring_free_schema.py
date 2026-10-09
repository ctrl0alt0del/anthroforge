"""Native sampled-path commands for protocol 0.4."""
try:
    from tools.authoring_schema_v04 import obj, array, enum, ref, S, I, N, operation
except ModuleNotFoundError:
    from authoring_schema_v04 import obj, array, enum, ref, S, I, N, operation


def definitions():
    sample = obj(dict(sample_id=S, co=ref('xyz')))
    tag = obj(dict(occurrence_id=S, point_id=S, sample_id=S, role=enum('START', 'END', 'MID', 'LOOP')))
    common = dict(space=enum('WORLD', 'ROOT_LOCAL'), structural=array(tag, 1, 4096))
    poly = obj(dict(**common, representation=enum('POLY'), samples=array(sample, 2, 4096)))
    knot = obj(dict(sample_id=S, co=ref('xyz'), handle_left=ref('xyz'), handle_right=ref('xyz')))
    bezier = obj(dict(**common, representation=enum('BEZIER'), knots=array(knot, 2, 4096),
                      resolution=dict(type='integer', minimum=2, maximum=4096)))
    attachment = obj(dict(point_id=S, parent_id=S, target=ref('attachment_surface_target'), position=ref('xyz'), attach_param=S, normal_offset=N), ['point_id'])
    return dict(free_path_input={'oneOf': [poly, bezier]}, free_path_attachment=attachment, attachment_surface_target=surface_target())


def surface_target():
    return obj(dict(type=enum('SCP', 'MUSCLE'), id=S, surface=enum('SCP_GEOMETRY', 'MUSCLE_BASE', 'MUSCLE_INFL'),
                    instance=enum('source', 'mirror')), ['type', 'id'])


def operations():
    revision = dict(expected_scene_revision=S); identified = dict(**revision, fiber_id=S, expected_path_revision=I)
    create = dict(**revision, topology=enum('OPEN', 'LOOP'), name=S, attachments=array(ref('free_path_attachment'), 2, 4096), settings=settings(), supports=array(ref('attachment_surface_target'), 0, 4096))
    rows = [operation('fibers.create_controlled', create, ['expected_scene_revision', 'attachments'])]
    rows += [operation('fibers.create_free', dict(**create, path=ref('free_path_input')), ['expected_scene_revision', 'attachments', 'path'])]
    rows += [operation('fibers.path_inspect', dict(fiber_id=S), ['fiber_id'])]
    rows += [operation('fibers.path_update', dict(**identified, path=ref('free_path_input')), [*identified, 'path'])]
    rows += [operation('fibers.supports_configure', dict(**revision, fiber_id=S, supports=array(ref('attachment_surface_target'), 0, 4096)), ['expected_scene_revision', 'fiber_id', 'supports'])]
    rows += [operation('fibers.rebind', dict(**revision, fiber_id=S), ['expected_scene_revision', 'fiber_id'])]
    rows += [operation('fibers.symmetry_configure', dict(**revision, fiber_id=S, mode=enum('INHERIT', 'NONE', 'EXPLICIT'), axis=enum('X', 'Y', 'Z'), origin=ref('xyz')), ['expected_scene_revision', 'fiber_id', 'mode'])]
    return rows + [operation('fibers.mode_configure', dict(**identified, mode=enum('FREE', 'CONTROLLED')), [*identified, 'mode'])]


def settings():
    bounded = lambda low, high: dict(type='integer', minimum=low, maximum=high)
    values = dict(node_count=bounded(8, 512), solver_version=bounded(1, 3), iterations_bake=bounded(1, 1000))
    values.update(collision_radius=dict(type='number', minimum=0), thickness=dict(type='number', minimum=0),
                  use_surface_routing=dict(type='boolean'), use_segment_collisions=dict(type='boolean'))
    return obj(values, [])


def extend(schema):
    schema['$defs'].update(definitions())
    schema['oneOf'].extend(operations())
    return schema
