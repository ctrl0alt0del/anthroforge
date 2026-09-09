"""Inspect the selected SCP through calibrated DSL views."""
from uuid import uuid4
import bpy
from ..app.queries.root import root_for_context
from ..app.authoring.api import execute
from ..adapters.authoring.scene import StaticScene
from .authoring_inspection import write_response


def send(root, scene, operation, **params):
    request = dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.'+operation, params=dict(scene_id=root.name, **params))
    result = execute(request, root, scene)
    write_response(result)
    return result


def selected(inventory, root, obj):
    if obj:
        matches = [r for r in inventory['instances'] if r['locator'] == obj.name and r['has_surface']]
        if len(matches) == 1:
            return matches[0]
    system = root.af_scp_system
    if 0 <= system.active_scp_index < len(system.scps):
        key = system.scps[system.active_scp_index].id
        matches = [r for r in inventory['instances'] if r['scp_id'] == key and r['has_surface'] and not r['mirror']]
        if len(matches) == 1:
            return matches[0]
    return None


class AF_OT_InspectSCPVisuals(bpy.types.Operator):
    bl_idname = 'af.inspect_scp_visuals'
    bl_label = 'Inspect selected SCP shape'
    bl_description = 'Create calibrated views of the selected SCP; assign persistent identities if needed'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = root_for_context(context)
        if root is None:
            return {'CANCELLED'}
        inventory = StaticScene(root, context.scene).capture_authoring()
        row = selected(inventory, root, context.active_object)
        if row is None:
            self.report({'WARNING'}, 'Select an SCP surface or its tree entry')
            return {'CANCELLED'}
        result = inspect(root, context.scene, row, inventory)
        self.report({'INFO'} if result['status'] == 'success' else {'WARNING'}, result['status'])
        return {'FINISHED'}


def inspect(root, scene, row, inventory):
    if not row['instance_id'] or not inventory['root_id']:
        initialized = send(root, scene, 'initialize', expected_scene_revision=inventory['revision'])
        if initialized['status'] != 'success':
            return initialized
        inventory = StaticScene(root, scene).capture_authoring()
        row = next(r for r in inventory['instances'] if r['locator'] == row['locator'])
    return send(root, scene, 'views', instance_id=row['instance_id'], expected_scene_revision=inventory['revision'])
