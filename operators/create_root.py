import bpy
from ..core.visualization.sync import register_sync

class AF_OT_CreateRoot(bpy.types.Operator):
    bl_idname = "af.create_root"
    bl_label = "Create AnthroForge Root"
    bl_description = "Creates AnthroForge root empty object"

    def execute(self, context):
      if "AF_ROOT" in bpy.data.objects:
          self.report({'WARNING'}, "AnthroForge Root already exists.")
          return {'CANCELLED'}

      root = bpy.data.objects.new("AF_ROOT", None)
      context.scene.collection.objects.link(root)

      root.empty_display_type = 'PLAIN_AXES'
      root.empty_display_size = 0.5

      root["anthroforge_root"] = True

      # initialize system container
      root.af_scp_system  # just ensure pointer exists

      self.report({'INFO'}, "AnthroForge Root created.")
      register_sync().sync_root_to_scene(root=root, scene=context.scene)
      return {'FINISHED'}
