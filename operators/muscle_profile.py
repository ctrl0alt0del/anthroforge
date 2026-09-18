"""Undoable profile actions; direct enum writes intentionally do not initialize."""
import bpy
from ..app.queries.root import root_for_context
from ..app.queries.vcp import active_muscle_from_context
from ..app.use_cases import muscle_profile as commands
from ..core.vcp.prop_update_guard import suppress_vcp_prop_updates

MODE_ITEMS = (("control_point", "Control Point", "Stored control point settings"),
              ("distributed", "Distributed", "Stored distributed settings"),
              ("section_profile", "Section Profile", "World-distance section depths"))


def _muscle(context, identity):
    root = root_for_context(context)
    muscle = next((item for item in root.af_vcp_system.muscles if item.id == identity), None) if root and identity else active_muscle_from_context(context)
    if root is None or muscle is None:
        raise ValueError("Muscle not found.")
    return root, muscle


def _execute(operator, context, configuration):
    try:
        root, muscle = _muscle(context, operator.muscle_id)
        commands.configure(root, context.scene, muscle.id, configuration(muscle))
        return {"FINISHED"}
    except (ValueError, RuntimeError) as error:
        operator.report({"ERROR"}, str(error))
        return {"CANCELLED"}


class AF_OT_MuscleProfileMode(bpy.types.Operator):
    bl_idname = "af.muscle_profile_mode"
    bl_label = "Inflation Mode"
    bl_options = {"REGISTER", "UNDO"}
    muscle_id: bpy.props.StringProperty(default="")
    mode: bpy.props.EnumProperty(items=MODE_ITEMS)

    def execute(self, context):
        if self.mode != "section_profile":
            return _legacy_mode(self, context)
        return _execute(self, context, lambda muscle: commands.mode_configuration(muscle, self.mode))


def _legacy_mode(operator, context):
    try:
        from ..app.runtime_api import sync_context
        from ..core.deps.dirty_hints import dirty_hints_for
        root, muscle = _muscle(context, operator.muscle_id)
        with commands.transaction(root, context.scene, muscle):
            commands.write_configuration(muscle, {"mode": operator.mode})
            sync_context(context, dirty_hints=dirty_hints_for("MUSCLE", {muscle.id}))
        return {"FINISHED"}
    except (ValueError, RuntimeError) as error:
        operator.report({"ERROR"}, str(error))
        return {"CANCELLED"}


class AF_OT_MuscleProfileReset(bpy.types.Operator):
    bl_idname = "af.muscle_profile_reset"
    bl_label = "Reset Profile"
    bl_options = {"REGISTER", "UNDO"}
    muscle_id: bpy.props.StringProperty(default="")
    depth: bpy.props.FloatProperty(name="Peak Depth (world units)", default=.05, min=0, max=10)

    def invoke(self, context, event):
        muscle = None
        try:
            _, muscle = _muscle(context, self.muscle_id)
            self.depth = max(commands.profile_from_muscle(muscle).depths)
        except ValueError:
            self.depth = commands._proposal(muscle)["depths"][1]["value"] if muscle else .05
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        return _execute(self, context, lambda muscle: commands.action_configuration(muscle, "reset", self.depth))


class AF_OT_MuscleProfileScale(bpy.types.Operator):
    bl_idname = "af.muscle_profile_scale"
    bl_label = "Scale Depths"
    bl_options = {"REGISTER", "UNDO"}
    muscle_id: bpy.props.StringProperty(default="")
    factor: bpy.props.FloatProperty(name="Depth Scale", default=1, min=0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        return _execute(self, context, lambda muscle: commands.action_configuration(muscle, "scale", self.factor))


class AF_OT_MuscleProfileSide(bpy.types.Operator):
    bl_idname = "af.muscle_profile_side"
    bl_label = "Swap Side"
    bl_description = "Reverse displacement relative to the ordered chart"
    bl_options = {"REGISTER", "UNDO"}
    muscle_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _execute(self, context, lambda muscle: commands.action_configuration(muscle, "side"))


class AF_MT_MuscleProfileMode(bpy.types.Menu):
    bl_label = "Inflation Mode"

    def draw(self, context):
        from ..ui.panels.muscle_profile import draw_mode_options
        draw_mode_options(self.layout, context)


CLASSES = (AF_OT_MuscleProfileMode, AF_OT_MuscleProfileReset, AF_OT_MuscleProfileScale, AF_OT_MuscleProfileSide, AF_MT_MuscleProfileMode)
