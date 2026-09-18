"""Small indexed skeleton/reference fixture for shared transfer integration checks."""
import json
from pathlib import Path
from uuid import uuid4
import bpy
import numpy as np
from test_authoring_v04 import setup, call
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.inventory import geometry_for
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.indexed_patches import bind, topology

REGION = '/skeleton_profiles/default/regions/origin'


def snapshot(root):
    return StaticScene(root, bpy.context.scene).capture_authoring()


def message(root, operation, **params):
    return dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.'+operation,
                params=dict(scene_id=root.name, expected_scene_revision=snapshot(root)['revision'], **params))


def fixture(root, directory):
    document = setup(root, directory)
    owner = document['skeleton_profiles']['default']['bindings']['origin']['instance_id']
    target = bpy.data.objects[next(r['label'] for r in snapshot(root)['instances'] if r['instance_id'] == owner)]
    target.scale = (1.4, .8, 1.2); target.rotation_euler.z = .3
    source = source_bone(target)
    muscles = [source_muscle('Reference_A', (5.1, .2, 0)), source_muscle('Reference_B', (4.8, -.2, .1))]
    inventory = snapshot(root); geometry = inventory['geometry'][owner]
    document['skeleton_profiles']['default']['regions']['origin']['query'] = whole_region(geometry)
    result = call(root, directory, 'draft', document, 0, document=document)
    assert result['status'] == 'success', result
    params = definition(document, source, muscles, geometry)
    return dict(document=document, owner=owner, target=target.name, source=source.name, muscles=[o.name for o in muscles], params=params)


def whole_region(geometry):
    patches = [dict(triangle=i, polygon=np.eye(3).tolist()) for i in range(len(geometry['triangles']))]
    return bind(geometry, patches)


def source_bone(target):
    obj = bpy.data.objects.new('Reference_bone', target.data.copy())
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (5, 0, 0)
    return obj


def source_muscle(name, location):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, location=location)
    obj = bpy.context.object; obj.name = name; obj.scale = (.15, .2, .45)
    obj.color = (.8, .25, .15, 1)
    return obj


def vertex_binding(geometry, vertex):
    triangle = next(row for row in geometry['triangles'] if vertex in row)
    return dict(tri_vidx=triangle, tri_weights=[float(v == vertex) for v in triangle])


def definition(document, source, muscles, target):
    geometry = geometry_for(source)
    origin = dict(object=source.name, topology_digest=topology(geometry))
    destination = dict(document_id=document['document_id'], expected_draft_revision=1, region=REGION, topology_digest=topology(target))
    pairs = [dict(id='corner_'+str(i), source=dict(origin, surface_binding=vertex_binding(geometry, i)),
                  target=dict(destination, surface_binding=vertex_binding(target, i))) for i in range(8)]
    annotation = dict(id='bone_landmark', label='synthetic attachment example', source=pairs[0]['source'])
    return dict(source_objects=[o.name for o in muscles], correspondences=pairs, annotations=[annotation],
                settings=dict(max_landmark_error=1e-6, samples_per_mesh=64))


def run(root, directory, operation, **params):
    return execute(message(root, operation, **params), root, bpy.context.scene, directory)


def read_preview(response):
    return json.loads(Path(response['assets'][0]['path']).read_text())
