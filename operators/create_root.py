import bpy

from ..app.runtime_api import sync_scene
from ..core.deps.dirty_hints import empty_dirty_hints
from ..core.utils import create_af_root
class AF_OT_CreateRoot(bpy.types.Operator):
    bl_idname = "af.create_root"
    bl_label = "Create AnthroForge Root"
    bl_description = "Creates AnthroForge root empty object"

    def execute(self, context):
      if "AF_ROOT" in bpy.data.objects:
          self.report({'WARNING'}, "AnthroForge Root already exists.")
          return {'CANCELLED'}
      root = create_af_root(context.scene)
      self.report({'INFO'}, "AnthroForge Root created.")
      sync_scene(root=root, scene=context.scene, dirty_hints=empty_dirty_hints())
      return {'FINISHED'}
