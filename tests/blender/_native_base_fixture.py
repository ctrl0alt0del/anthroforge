"""Three SCPs and a continuous underside spanning contacts and free space."""
import json
from pathlib import Path
import bpy
from test_authoring_v04 import setup, call
from _transfer_fixture import snapshot, run, whole_region
from anthroforge.adapters.authoring.transfer import capture


def fixture(root, directory):
    document = setup(root, directory); inventory = snapshot(root)
    for name, definition in document['skeleton_profiles']['default']['regions'].items():
        binding = document['skeleton_profiles']['default']['bindings'][name]
        definition['query'] = whole_region(inventory['geometry'][binding['instance_id']])
    assert call(root, directory, 'draft', document, 0, document=document)['status'] == 'success'
    mesh = bpy.data.meshes.new('Whole underside'); mesh.from_pydata(
        [(.5, -.2, 2), (.5, .2, 2), (.5, .2, -2), (.5, -.2, -2)], [], [(0, 1, 2), (0, 2, 3)])
    obj = bpy.data.objects.new('Whole underside', mesh); bpy.context.scene.collection.objects.link(obj)
    row = capture(bpy.context.scene, [obj.name])[obj.name]
    definition = dict(source_object=obj.name, topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'],
                      heads=[dict(id='main', label='Synthetic')], anatomical_note='Whole underside, not only contact areas.',
                      patches=[dict(id='main', head_ids=['main'], source_triangles=[0, 1], boundary_vertex_ids=[0, 1, 2, 3])])
    return document, obj, definition


def plan_params(document, base_id):
    fields = dict(document_id=document['document_id'], expected_draft_revision=1, across=[0, 1], max_distance=.05, facing=[1, 0, 0])
    bindings = [dict(fields, role=role, region='/skeleton_profiles/default/regions/'+name)
                for role, name in [('origin', 'origin'), ('insertion', 'insertion'), ('route', 'guide')]]
    return dict(base_id=base_id, tolerance=.08, candidate_count=3, samples_per_fiber=17, max_middle_points=0,
                collision_radius=.002, max_fibers=2, solver_budget_ms=10000, parts=[dict(patch_id='main', bindings=bindings)])


def planned(root, folder):
    document, obj, definition = fixture(root, folder)
    base = run(root, folder, 'define_base', **definition); assert base['status'] == 'success', base
    params = plan_params(document, base['base_surface']['id'])
    result = run(root, folder, 'plan_base_fibers', **params); assert result['status'] == 'success', result
    return result, params, obj


def read_asset(result):
    return json.loads(Path(result['assets'][0]['path']).read_text())


def prepared_square(root, folder, definition):
    arcs = [dict(id='a'+str(i), vertex_ids=[i, (i+1)%4], role='side', segments=3) for i in range(4)]
    params = {k: definition[k] for k in ('source_object', 'topology_digest', 'geometry_digest', 'heads')}
    params.update(arcs=arcs, patches=[dict(id='main', head_ids=['main'], source_triangles=[0, 1],
                                         boundary=[dict(arc=a['id']) for a in arcs])], settings=dict(rings=2, iterations=0))
    result = run(root, folder, 'prepare_base', **params); assert result['status'] == 'success', result
    return result, read_asset(result)
