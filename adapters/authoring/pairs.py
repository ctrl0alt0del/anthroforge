"""Authoring adapter to the same service used by the Blender panel."""
from contextlib import contextmanager
import json
from ...core.muscle_pairs import runtime, configuration

RECEIPTS = 'af_pair_detection_receipts'


def inspect(scene):
    return runtime.inspect(scene.scene, scene.root)


def refresh(scene):
    runtime.refresh(scene.scene, scene.root, explicit=True)
    return inspect(scene)


def footprint(scene, index, revision):
    result = runtime.footprint(scene.scene, scene.root, index, revision)
    return dict(domains=result['domains'], result_revision=revision, pair_index=index,
        fragments={k: result['fragment_array'][k].tolist() for k in result['fragment_array'].dtype.names},
        polygons={k: result['point_array'][k].tolist() for k in result['point_array'].dtype.names})


def order_footprint(scene, index, revision):
    result = runtime.footprint(scene.scene, scene.root, index, revision, order=True)
    return dict(domains=result['domains'], result_revision=revision, pair_index=index,
        fragments={k: result['fragment_array'][k].tolist() for k in result['fragment_array'].dtype.names},
        polygons={k: result['point_array'][k].tolist() for k in result['point_array'].dtype.names})


def receipt(scene, request_id, value=None):
    records = json.loads(scene.root.get(RECEIPTS, '{}'))
    if value is not None:
        records[request_id] = value; scene.root[RECEIPTS] = json.dumps(records, sort_keys=True)
    return records.get(request_id)


@contextmanager
def mutation(scene, change, guards=None):
    from ...core.muscle_relationships import service
    guards = guards or {}
    previous = scene.root.get(RECEIPTS)
    try:
        with service.mutation((scene.scene, scene.root), change, guards.get('expected_relationship_revision'), guards.get('expected_result_revision')):
            runtime.refresh(scene.scene, scene.root, explicit=bool({'stacking', 'relationships'} & change.keys()))
            yield
    except BaseException:
        configuration.restore(scene.root, RECEIPTS, previous)
        runtime.refresh(scene.scene, scene.root)
        raise
