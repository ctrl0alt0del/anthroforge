"""Capture reference meshes and publish disposable, independently owned review copies."""
from contextlib import contextmanager
import bpy
from .inventory import geometry_for
from ...core.authoring.codec import digest, encode
from ...core.authoring.errors import require
from ...core.authoring.indexed_patches import topology

MAX_VERTICES = 500000


def capture(scene, names):
    require(len(names) <= 384, 'TRANSFER_OBJECT_BUDGET')
    rows, count = {}, 0
    for name in names:
        obj = scene.objects.get(name)
        require(obj is not None and obj.type == 'MESH', 'TRANSFER_SOURCE_NOT_FOUND', name)
        geometry = geometry_for(obj)
        require(bool(geometry['triangles']), 'TRANSFER_SOURCE_EMPTY', name)
        count += len(geometry['vertices'])
        require(count <= MAX_VERTICES, 'TRANSFER_VERTEX_BUDGET')
        rows[name] = dict(geometry=geometry, topology_digest=topology(geometry),
                         geometry_digest=digest(geometry), color=list(obj.color))
    return rows


def group(root, scene, identity):
    matches = [c for c in scene.collection.children_recursive if c.get('af_transfer_id') == identity
               and c.get('af_transfer_root') == (root.get('af_authoring_id') or root.name)]
    require(len(matches) <= 1, 'TRANSFER_REVIEW_DUPLICATED')
    return matches[0] if matches else None


@contextmanager
def publish(root, scene, record):
    existing = group(root, scene, record['id'])
    if existing is not None:
        yield verify_group(existing, record)
        return
    collection = create_group(root, scene, record)
    try:
        yield group_info(collection, False)
    except BaseException:
        remove_group(collection)
        raise


def create_group(root, scene, record):
    collection = bpy.data.collections.new('AF_TRANSFER_REVIEW_'+record['id'][:12])
    try:
        scene.collection.children.link(collection)
        collection['af_transfer_id'] = record['id']
        collection['af_transfer_root'] = root.get('af_authoring_id') or root.name
        collection['af_transfer_manifest'] = encode(manifest(record))
        for row in record['result']['meshes']:
            create_object(collection, row, record['id'])
        return collection
    except BaseException:
        remove_group(collection)
        raise


def manifest(record):
    return dict(version=record['result'].get('version', 'skeleton_transfer.v1'), preview_id=record['id'], experimental=False,
                method=record['result']['method'], definition=record['definition'],
                field=record['result']['field'], status=record['result']['status'],
                annotations=record['result']['annotations'], validation=record['result']['validation'],
                shape_preservation=record['result'].get('shape_preservation'), field_role=record['result'].get('field_role', 'final_mapping'),
                annotation_mapping=record['result'].get('annotation_mapping', 'shared_field'))


def create_object(collection, row, identity):
    mesh, obj = bpy.data.meshes.new('Transfer review'), None
    try:
        mesh.from_pydata(row['vertices'], [], row['triangles']); mesh.update()
        obj = bpy.data.objects.new('TRANSFER_'+row['source_object'], mesh)
        collection.objects.link(obj)
        decorate(obj, row, identity)
        obj['af_transfer_geometry_digest'] = digest(geometry_for(obj))
        return obj
    except BaseException:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


def decorate(obj, row, identity):
    obj.color = row['color']
    obj.display_type = 'TEXTURED'
    obj.hide_viewport = obj.hide_render = False
    obj.hide_set(False)
    obj['af_transfer_id'] = identity
    obj['af_transfer_source'] = row['source_object']
    obj['af_transfer_experimental'] = False
    obj['af_transfer_quality'] = encode(row['quality'])
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    bpy.context.view_layer.update()


def verify_group(collection, record):
    objects = list(collection.objects)
    expected = {row['source_object'] for row in record['result']['meshes']}
    require(len(objects) == len(expected) and {o.get('af_transfer_source') for o in objects} == expected,
            'TRANSFER_REVIEW_EDITED', 'Existing review collection membership changed.')
    for obj in objects:
        require(obj.get('af_transfer_geometry_digest') == digest(geometry_for(obj)), 'TRANSFER_REVIEW_EDITED', obj.name)
    return group_info(collection, True)


def group_info(collection, reused):
    return dict(collection=collection.name, reused=reused,
                objects=[dict(name=obj.name, source_object=obj['af_transfer_source']) for obj in collection.objects])


def remove_group(collection):
    for obj in list(collection.objects):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(collection)
