"""Evaluated mesh subjects and neighboring native muscles for calibrated inspection."""
import numpy as np
import bpy
from mathutils import Vector
from ...core.authoring.visual_context import bounds, box_gap
from ...core.authoring.errors import require
from .transfer import capture


def object_box(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points = np.array([tuple(evaluated.matrix_world @ Vector(p)) for p in evaluated.bound_box])
    return np.array([points.min(0), points.max(0)])


def candidates(port, known):
    for obj in port.scene.objects:
        if obj.type != 'MESH' or obj.name in known:
            continue
        if obj.get('af_muscle_proxy'):
            if obj.get('af_root_name') == port.root.name and obj.get('af_muscle_surface') == 'INFL':
                yield obj
        elif not obj.hide_get() and not obj.hide_viewport:
            yield obj


def extend(port, inventory, names):
    names = sorted(set(names)); rows = capture(port.scene, names) if names else {}
    geometry = dict(inventory['geometry'])
    instances = [r for r in inventory['instances'] if r['instance_id'] not in {'OBJECT:'+n for n in names}]
    sources = dict(inventory.get('visual_objects', {}))
    for name, row in rows.items():
        key = 'OBJECT:'+name; geometry[key] = row['geometry']; sources[key] = name
        instances.append(dict(instance_id=key, locator=name, scp_id='', has_surface=True))
    return dict(inventory, geometry=geometry, instances=instances, visual_objects=sources)


def prepare(port, inventory, params):
    require(('instance_id' in params) != ('source_object' in params), 'VIEW_SUBJECT_AMBIGUOUS')
    owner = params.get('instance_id', 'OBJECT:'+params.get('source_object', ''))
    names = params.get('context_objects', [])+([params['source_object']] if 'source_object' in params else [])
    current = extend(port, inventory, names)
    require(owner in current['geometry'], 'SURFACE_DOMAIN_UNAVAILABLE', owner)
    box = bounds(current['geometry'][owner]); distance = params.get('neighbor_distance', float(np.linalg.norm(np.ptp(box, axis=0)))*.15)
    if params.get('automatic_context', not {'context_ids', 'context_objects'} & set(params)):
        known = {r.get('locator') for r in current['instances']}
        neighbors = [o.name for o in candidates(port, known) if box_gap(box, object_box(o)) <= distance]
        current = extend(port, current, neighbors)
    return current, owner
