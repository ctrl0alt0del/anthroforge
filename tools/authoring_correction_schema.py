"""Strict contracts for world-space collision diagnostics and reference repair."""
try:
    from tools.authoring_schema_v04 import S, I, B, ref, obj, array, operation, enum
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, B, ref, obj, array, operation, enum


def positive():
    return dict(type='number', exclusiveMinimum=0)


def settings(correction=False):
    fields = dict(tolerance=positive(), validation_samples=dict(type='integer', minimum=64, maximum=60000))
    if not correction:
        return obj(fields, ['tolerance'])
    fields.update(influence_radius=positive(), max_displacement=positive(), protection_blend=positive(),
                  fit_clearance=dict(type='number', minimum=0), smoothness=dict(type='number', minimum=0, maximum=100),
                  centers=dict(type='integer', minimum=4, maximum=48), max_iterations=dict(type='integer', minimum=1, maximum=150),
                  max_seconds=dict(type='number', minimum=1, maximum=180), max_volume_change=dict(type='number', minimum=0, maximum=1),
                  cleanup=enum('none', 'exact'), influences=array(obj(dict(center=ref('xyz'), radius=positive())), 0, 16))
    return obj(fields, ['tolerance', 'influence_radius', 'max_displacement'])


def operations():
    common = dict(expected_scene_revision=S, source_object=S, topology_digest=S, geometry_digest=S, obstacle_instance_ids=array(S, 1, 16))
    rows = [operation('anatomy.transfer_collisions', dict(**common, settings=settings()), list(common)+['settings'])]
    band = obj(dict(id=S, vertex_indices=array(I, 1, 30000)))
    contact = obj(dict(id=S, source_binding=ref('surface_binding'), obstacle_instance_id=S, target_binding=ref('surface_binding')))
    fields = dict(**common, settings=settings(True), guard_instance_ids=array(S, 0, 16), protected_bands=array(band, 0, 64), contacts=array(contact, 0, 128))
    rows.append(operation('anatomy.transfer_correct_preview', fields, list(common)+['settings']))
    fields = dict(expected_scene_revision=S, preview_id=S)
    return rows+[operation('anatomy.transfer_correct_publish', fields, list(fields))]+attachments()


def attachments():
    try:
        from tools.authoring_attachment_schema import operations
    except ModuleNotFoundError:
        from authoring_attachment_schema import operations
    return operations()
