import bpy

from ..app.use_cases.fiber_surface_create import (
    create_fiber_surface,
    create_muscle_from_fiber_surface,
    convert_muscle_to_fiber_surface,
    recompute_fiber_surface,
    select_fiber_surface_sources,
)


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_CreateFiberSurface(bpy.types.Operator):
    bl_idname = "af.create_fiber_surface"
    bl_label = "Create Fiber Surface"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty(name="Name", default="")
    close_across_fibers: bpy.props.BoolProperty(name="Close Across Fibers", default=False)
    use_mirrored_rows: bpy.props.BoolProperty(name="Use Mirrored Rows", default=False)

    def execute(self, context):
        result = create_fiber_surface(context, self.name, self.close_across_fibers, self.use_mirrored_rows)
        return _finish(self, result)


class AF_OT_CreateMuscleFromFiberSurface(bpy.types.Operator):
    bl_idname = "af.create_muscle_from_fiber_surface"
    bl_label = "Create Muscle From Fiber Surface"
    bl_options = {"REGISTER", "UNDO"}
    surface_id: bpy.props.StringProperty(default="")
    name: bpy.props.StringProperty(name="Name", default="")

    def execute(self, context):
        return _finish(self, create_muscle_from_fiber_surface(context, self.surface_id, self.name))


class AF_OT_RecomputeFiberSurface(bpy.types.Operator):
    bl_idname = "af.recompute_fiber_surface"
    bl_label = "Recompute Fiber Surface"
    surface_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, recompute_fiber_surface(context, self.surface_id))


class AF_OT_SelectFiberSurfaceSources(bpy.types.Operator):
    bl_idname = "af.select_fiber_surface_sources"
    bl_label = "Select Fiber Surface Sources"
    surface_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, select_fiber_surface_sources(context, self.surface_id))


class AF_OT_ConvertMuscleToFiberSurface(bpy.types.Operator):
    bl_idname = "af.convert_muscle_to_fiber_surface"
    bl_label = "Convert Muscle to Fiber Surface"
    bl_options = {"REGISTER", "UNDO"}
    muscle_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        return _finish(self, convert_muscle_to_fiber_surface(context, self.muscle_id))
