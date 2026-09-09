"""Execute a protocol request from a Blender Text datablock."""
import json
import bpy
from ..app.authoring.api import execute
from ..app.queries.root import root_for_context


class AF_OT_ExecuteAuthoringDSL(bpy.types.Operator):
    bl_idname = "af.execute_authoring_dsl"
    bl_label = "Execute AnthroForge DSL Request"
    bl_options = {"REGISTER", "UNDO"}
    text_name: bpy.props.StringProperty(name="Request Text")

    def invoke(self, context, event):
        text = getattr(context.space_data, 'text', None)
        if text is not None:
            self.text_name = text.name
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop_search(self, 'text_name', bpy.data, 'texts')

    def execute(self, context):
        text = bpy.data.texts.get(self.text_name) or getattr(context.space_data, "text", None)
        root = root_for_context(context)
        if text is None or root is None:
            self.report({"ERROR"}, "Choose a JSON request Text and an AF_ROOT")
            return {"CANCELLED"}
        result = execute(text.as_string(), root, context.scene)
        output = bpy.data.texts.get("AnthroForge DSL Response.json") or bpy.data.texts.new("AnthroForge DSL Response.json")
        output.clear()
        output.write(json.dumps(result, indent=2))
        self.report({"INFO"} if result["status"] == "success" else {"WARNING"}, result["status"])
        return {"FINISHED"}
