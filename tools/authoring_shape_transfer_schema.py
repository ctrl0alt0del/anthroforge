"""Opt-in shape matching on one jointly fitted anatomical family per request."""
try:
    from tools.authoring_schema_v04 import S, I, obj, array
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, obj, array


def number(low, high=None):
    return dict(type='number', minimum=low, **(dict(maximum=high) if high is not None else {}))


def settings():
    positive = dict(type='number', exclusiveMinimum=0)
    return obj(dict(radius_fraction=dict(**positive, maximum=2), cluster_radius_fraction=dict(**positive, maximum=1),
                    bridge_fraction=number(0, .1), shape_strength=dict(**positive, maximum=1000), collision_strength=number(0, 1000),
                    clearance=number(0), convergence=positive, far_influence=number(0, 1),
                    max_iterations=dict(type='integer', minimum=1, maximum=1000)), [])


def specification():
    band = obj(dict(source_object=S, topology_digest=S, geometry_digest=S, vertex_indices=array(I, 1, 100000)))
    return obj(dict(family_id=S, protected_bands=array(band, 1, 128), obstacle_instance_ids=array(S, 1, 32),
                    tolerance=dict(type='number', exclusiveMinimum=0), validation_samples=dict(type='integer', minimum=64, maximum=60000),
                    settings=settings()), ['family_id', 'protected_bands', 'obstacle_instance_ids', 'tolerance'])
