"""Face-selection draft over a temporary base; authored geometry is never edited."""
from dataclasses import dataclass, field
import bpy
import numpy as np
from ..core.muscle_relationships import service, store
from ..core.muscle_relationships.identity import token
from ..core.muscle_pairs import runtime

SESSIONS = {}
TAG = 'af_relationship_region_preview'


@dataclass
class RegionDraft:
    root: object
    scene: object
    relationship: str
    revision: int
    result_revision: str
    domain: object
    selected: set = field(default_factory=set)
    objects: list = field(default_factory=list)
    previous_active: object = None
    previous_selected: tuple = ()
    suspended: bool = False
    selection_flags: tuple = ()


def begin(root, scene, identity):
    cancel(root); state = runtime.inspect(scene, root); document = store.read(root)
    row = document['records'][identity]; cover = row['intent'].get('cover') or row.get('covering')
    domains, _ = service.inputs((scene, root), state['result_revision'])
    domain = next((d for d in domains if (d.key.muscle, d.key.instance, d.key.side) == tuple(cover or ())), None)
    if domain is None: raise ValueError('RELATIONSHIP_SUPPORTED_COVER_REQUIRED')
    faces = row['intent'].get('region', {}).get('faces', ()) if row['intent'].get('region') else ()
    draft = RegionDraft(root, scene, identity, document['revision'], state['result_revision'], domain, set(map(tuple, faces)),
        previous_active=bpy.context.view_layer.objects.active, previous_selected=tuple(bpy.context.selected_objects))
    SESSIONS[root.session_uid] = draft
    try: create(draft); return draft
    except BaseException: cancel(root); raise


def temporary_mesh(draft, name, points, faces, color):
    mesh = bpy.data.meshes.new(name); mesh.from_pydata(points, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh); draft.scene.collection.objects.link(obj)
    obj[TAG] = True; obj['af_relationship_root'] = draft.root.name; obj.hide_render = True
    obj.color = color; obj.show_in_front = True; draft.objects.append(obj)
    return obj


def create(draft):
    obj = temporary_mesh(draft, 'Support region · select faces', draft.domain.base, draft.domain.faces, (.15, .6, .85, 1))
    for p, part, source in zip(obj.data.polygons, draft.domain.parts, draft.domain.sources): p.select = (int(part), int(source)) in draft.selected
    if bpy.context.object and bpy.context.object.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    for other in tuple(bpy.context.selected_objects): other.select_set(False)
    obj.select_set(True); bpy.context.view_layer.objects.active = obj
    footprint(draft)
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bpy.ops.object.mode_set(mode='EDIT')
    draft.selection_flags = tuple(p.select for p in obj.data.polygons)
    if not bpy.app.timers.is_registered(sync_selection): bpy.app.timers.register(sync_selection, first_interval=.1)


def footprint(draft):
    state = runtime.inspect(draft.scene, draft.root)
    pair = next(p for p in state['pairs'] if p['relationship_id'] == draft.relationship)
    data = runtime.footprint(draft.scene, draft.root, pair['index'], draft.result_revision, order=True)
    cover = next(int(k) for k, v in data['domains'].items() if token(v['key']) == token(vars(draft.domain.key)))
    points, faces = [], []
    for fragment in data['fragment_array']:
        if int(fragment['provider']) != cover or fragment['gap_max'] <= 1e-6: continue
        start, count = int(fragment['start']), int(fragment['count'])
        values = data['point_array'][start:start+count]['world_provider']
        faces.append(tuple(range(len(points), len(points)+count))); points.extend(values.tolist())
    overlay = temporary_mesh(draft, 'Overlap footprint', points, faces, (1., .6, .1, 1.))
    overlay.display_type = 'WIRE'; overlay.hide_select = True


def selection(draft):
    obj = draft.objects[0]; obj.update_from_editmode()
    points = np.empty((len(obj.data.vertices), 3), dtype=np.float32); obj.data.vertices.foreach_get('co', points.ravel())
    faces = np.asarray([tuple(p.vertices) for p in obj.data.polygons], dtype=np.int64)
    if not np.array_equal(points, draft.domain.base.astype(np.float32)): raise ValueError('RELATIONSHIP_PREVIEW_GEOMETRY_EDITED')
    if not np.array_equal(faces, draft.domain.faces) or not np.array_equal(np.asarray(obj.matrix_world), np.eye(4)): raise ValueError('RELATIONSHIP_PREVIEW_GEOMETRY_EDITED')
    return {(int(part), int(source)) for p, part, source in zip(obj.data.polygons, draft.domain.parts, draft.domain.sources) if p.select}


def apply(root):
    draft = SESSIONS.get(root.session_uid)
    if draft is None: raise ValueError('RELATIONSHIP_NO_REGION_SESSION')
    selected = selection(draft)
    if not selected: raise ValueError('RELATIONSHIP_EMPTY_SELECTION')
    change = dict(relationships=[dict(id=draft.relationship, region=[list(f) for f in sorted(selected)])])
    service.configure((draft.scene, root), change, draft.revision, draft.result_revision)
    cancel(root)


def remove_objects(draft):
    if bpy.context.object in draft.objects and bpy.context.object.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    for obj in draft.objects:
        try:
            mesh = obj.data; bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0: bpy.data.meshes.remove(mesh)
        except ReferenceError: pass
    draft.objects.clear()


def cancel(root):
    draft = SESSIONS.pop(root.session_uid, None)
    if draft is None: return
    remove_objects(draft)
    for obj in draft.previous_selected:
        try: obj.select_set(True)
        except (ReferenceError, RuntimeError): pass
    try: bpy.context.view_layer.objects.active = draft.previous_active
    except ReferenceError: pass


def clear():
    for draft in tuple(SESSIONS.values()):
        remove_objects(draft)
    SESSIONS.clear()
    if bpy.app.timers.is_registered(sync_selection): bpy.app.timers.unregister(sync_selection)


def sync_selection():
    for draft in tuple(SESSIONS.values()):
        if not draft.suspended and draft.objects: synchronize_faces(draft)
    return .1 if SESSIONS else None


def synchronize_faces(draft):
    import bmesh
    obj = draft.objects[0]
    if obj.mode != 'EDIT': return
    bm = bmesh.from_edit_mesh(obj.data); faces = list(bm.faces)
    if len(faces) != len(draft.domain.parts): return
    flags = tuple(f.select for f in faces)
    if flags == draft.selection_flags: return
    groups = list(zip(draft.domain.parts, draft.domain.sources)); changed = {}
    for group, before, after in zip(groups, draft.selection_flags, flags):
        if before != after: changed[group] = changed.get(group, False) or after
    for face, group in zip(faces, groups):
        if group in changed: face.select_set(changed[group])
    draft.selection_flags = tuple(f.select for f in faces); bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
