import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from ..core.importing import import_package_from_blend, import_vcp_from_blend


def _summary(result):
    parts = [f"{result.scp_count} SCP", f"{result.fiber_count} Fiber", f"{result.muscle_count} Muscle"]
    parts += [f"{result.blob_count} Blob", f"{result.shortcut_count} Shortcut"]
    return "Imported " + ", ".join(parts) + "."


def _vcp_summary(result):
    parts = [f"{result.fiber_count} Fiber", f"{result.muscle_count} Muscle", f"{result.blob_count} Blob"]
    return "Imported " + ", ".join(parts) + "."


def _report_warnings(operator, result):
    for warning in result.warnings[:5]:
        operator.report({"WARNING"}, warning)


class AF_OT_ImportPackage(bpy.types.Operator, ImportHelper):
    bl_idname = "af.import_package"
    bl_label = "Import AF Package"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def execute(self, context):
        try:
            result = import_package_from_blend(self.filepath, context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _report_warnings(self, result)
        self.report({"INFO"}, _summary(result))
        return {"FINISHED"}


class AF_OT_ImportVCP(bpy.types.Operator, ImportHelper):
    bl_idname = "af.import_vcp"
    bl_label = "Import AF VCP"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".blend"
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def execute(self, context):
        try:
            result = import_vcp_from_blend(self.filepath, context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _report_warnings(self, result)
        self.report({"INFO"}, _vcp_summary(result))
        return {"FINISHED"}
