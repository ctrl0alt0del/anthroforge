"""Small designer controls over the same candidate protocol used by AI."""
import json
from pathlib import Path
from uuid import uuid4
import bpy
from ..app.queries.root import root_for_context
from ..app.authoring.api import execute


def response_text():
    text = bpy.data.texts.get('AnthroForge DSL Response.json')
    try:
        return json.loads(text.as_string()) if text else {}
    except (ValueError, TypeError):
        return {}


def write_response(result):
    text = bpy.data.texts.get('AnthroForge DSL Response.json') or bpy.data.texts.new('AnthroForge DSL Response.json')
    text.clear()
    text.write(json.dumps(result, indent=2))


class AF_OT_InspectAuthoringCandidate(bpy.types.Operator):
    bl_idname = 'af.inspect_authoring_candidate'
    bl_label = 'Inspect candidate'
    document_id: bpy.props.StringProperty()
    candidate_id: bpy.props.StringProperty()

    def execute(self, context):
        root = root_for_context(context)
        if root is None:
            return {'CANCELLED'}
        params = dict(scene_id=root.name, document_id=self.document_id, candidate_id=self.candidate_id)
        request = dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.inspect_candidate', params=params)
        write_response(execute(request, root, context.scene))
        return {'FINISHED'}


class AF_OT_AdoptAuthoringCandidate(bpy.types.Operator):
    bl_idname = 'af.adopt_authoring_candidate'
    bl_label = 'Adopt resolved binding'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from ..adapters.authoring.scene import StaticScene
        root, candidate = root_for_context(context), response_text().get('candidate')
        if root is None or not candidate or 'draft_revision' not in candidate:
            return {'CANCELLED'}
        revision = StaticScene(root, context.scene).capture_authoring()['revision']
        params = dict(scene_id=root.name, document_id=candidate['document_id'], candidate_id=candidate['id'], mode='resolved', expected_draft_revision=candidate['draft_revision'], expected_scene_revision=revision)
        request = dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.adopt_binding', params=params)
        result = execute(request, root, context.scene)
        write_response(result)
        self.report({'INFO'} if result['status'] == 'success' else {'WARNING'}, result['status'])
        return {'FINISHED'}


class AF_PT_AuthoringInspector(bpy.types.Panel):
    bl_label = 'DSL Authoring'
    bl_idname = 'AF_PT_authoring_inspector'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AnthroForge'

    def draw(self, context):
        result = response_text()
        self.layout.operator('af.execute_authoring_dsl')
        self.layout.operator('af.inspect_scp_visuals')
        self.layout.label(text='Latest result: '+result.get('status', 'No response'))
        draw_candidates(self.layout, result)
        for diagnostic in result.get('diagnostics', [])[:4]:
            self.layout.label(text=diagnostic.get('code', ''), icon='ERROR')
        draw_assets(self.layout, result)


def draw_candidates(layout, result):
    candidate = result.get('candidate', {})
    if candidate.get('checks', {}).get('state') == 'resolved':
        layout.operator('af.adopt_authoring_candidate')
    for row in result.get('candidates', [])[:12]:
        op = layout.operator('af.inspect_authoring_candidate', text=row['id'][:12]+' — '+row['checks']['state'])
        op.candidate_id = row['id']
        op.document_id = row.get('document_id', '')


def draw_assets(layout, result):
    assets = result.get('assets', [])
    ordered = [a for a in assets if a.get('kind') == 'inspection_index']+[a for a in assets if a.get('kind') == 'image']
    for asset in ordered[:9]:
        op = layout.operator('wm.url_open', text='Open all calibrated views' if asset['kind'] == 'inspection_index' else 'Open inspection view')
        op.url = Path(asset['path']).as_uri()
