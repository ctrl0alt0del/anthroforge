import bpy


class AF_OT_CreateRoot(bpy.types.Operator):
    bl_idname = "af.create_root"
    bl_label = "Create AnthroForge Root"
    bl_description = "Creates AnthroForge root empty object"

    def execute(self, context):

        if "AF_ROOT" in bpy.data.objects:
            self.report({'WARNING'}, "AF_ROOT already exists.")
            return {'CANCELLED'}

        root = bpy.data.objects.new("AF_ROOT", None)
        context.scene.collection.objects.link(root)

        root.empty_display_type = 'PLAIN_AXES'
        root.empty_display_size = 0.5

        root["anthroforge_root"] = True

        self.report({'INFO'}, "AF_ROOT created.")
        return {'FINISHED'}
