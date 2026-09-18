"""Versioned base selections, guarded against edits to the transferred reference."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import world
from ...core.authoring.base_definition import define
from .transfers import capture, key
from .base_surfaces import serial


def source(service, spec):
    row = capture(service, [spec['source_object']])[spec['source_object']]
    require(row['topology_digest'] == spec['topology_digest'], 'STALE_BASE_TOPOLOGY')
    require(row['geometry_digest'] == spec['geometry_digest'], 'STALE_BASE_GEOMETRY')
    return row


def define_base(service, request):
    params = request['params']; service.check(params); vertices, triangles, spec = input_mesh(service, params)
    result = define(vertices, triangles, params['heads'], params['patches'])
    result['source'] = spec
    result['anatomical_note'] = params['anatomical_note']
    for patch in result['patches']:
        patch['spatial_quality'] = service.scene.base_mesh_quality(patch['vertices'], patch['triangles'])
        require(not patch['spatial_quality']['nonadjacent_bvh_overlap_pairs'], 'BASE_SPATIAL_OVERLAP')
    result['id'] = digest(result); service.store.put('muscle_bases', key(service, result['id']), serial(result))
    return dict(base_surface=dict(id=result['id'], version=result['version'], heads=result['heads'],
                                  patch_ids=[p['id'] for p in result['patches']]),
                assets=[service.store.asset(result, 'muscle_base')])


def input_mesh(service, params):
    if 'prepared_base_id' in params:
        result = service.store.get('base_previews', key(service, params['prepared_base_id']))
        require(result is not None, 'BASE_PREVIEW_NOT_FOUND'); source(service, result['source'])
        require(result['status'] == 'geometry_candidate', 'BASE_CHART_UNRESOLVED')
        require(params['heads'] == result['heads'], 'BASE_PREVIEW_HEADS_CHANGED')
        return result['vertices'], result['triangles'], result['source']
    row = source(service, params)
    return world(row['geometry']), row['geometry']['triangles'], {k: params[k] for k in ('source_object', 'topology_digest', 'geometry_digest')}


def load_base(service, identity):
    result = service.store.get('muscle_bases', key(service, identity))
    require(result is not None, 'BASE_NOT_FOUND'); source(service, result['source'])
    return result
