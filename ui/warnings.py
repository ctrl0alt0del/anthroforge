"""Token-only, save-cleared UI projection of the file-wide Python repository."""
import bpy
from time import perf_counter
from bpy.app.handlers import persistent
from ..core.warnings.session import REPOSITORY
from ..core.warnings.repository import sort_key

_UNSUBSCRIBE = None
_PROJECTING = False
_LAST_REFRESH = 0.0


def request_refresh(repository=None):
    pending = any(row['status'] in ('PENDING', 'CHECKING') for row in REPOSITORY.states.values())
    if not pending or perf_counter()-_LAST_REFRESH >= .1: return refresh()
    if not bpy.app.timers.is_registered(_refresh_when_ready):
        bpy.app.timers.register(_refresh_when_ready, first_interval=max(0., .1-(perf_counter()-_LAST_REFRESH)))


def select_index(manager, context):
    if _PROJECTING or not (0 <= manager.af_warning_index < len(manager.af_warning_rows)):
        return
    from ..core.visualization.warning_selection import select_warning
    select_warning(context, manager.af_warning_rows[manager.af_warning_index].token)


class AF_WarningRow(bpy.types.PropertyGroup):
    token: bpy.props.StringProperty(options={"SKIP_SAVE"})


class AF_OT_SelectWarning(bpy.types.Operator):
    bl_idname = "af.select_warning"
    bl_label = "Select warning target"
    token: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        from ..core.visualization.warning_selection import select_warning
        if not select_warning(context, self.token):
            self.report({"WARNING"}, "Warning target is stale or unavailable; checking again.")
            return {"CANCELLED"}
        return {"FINISHED"}


class AF_UL_Warnings(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = REPOSITORY.records.get(item.token)
        if row is None:
            return
        ref = row.entity
        label = f"{ref.scene_label} / {ref.root_label} / {ref.label} [{ref.native_id}]: {row.summary}"
        op = layout.operator("af.select_warning", text=label, icon="ERROR", emboss=False)
        op.token = row.id


def draw(layout, context):
    box = layout.box()
    manager = context.window_manager
    box.prop(manager, "af_warnings_expanded", text=f"File warnings ({len(REPOSITORY.records)})",
             icon="TRIA_DOWN" if manager.af_warnings_expanded else "TRIA_RIGHT", emboss=False)
    status = REPOSITORY.status()
    if not status["complete"]:
        box.label(text=status_label(status), icon="TIME" if not status["counts"]["FAILED"] else "ERROR")
    if manager.af_warnings_expanded:
        box.label(text="All loaded scenes and AnthroForge roots")
        box.template_list("AF_UL_Warnings", "", manager, "af_warning_rows", manager, "af_warning_index", rows=5)


def status_label(status):
    counts = status["counts"]
    if counts["FAILED"] or status["discovery"] == "FAILED":
        return "Check failed or attachment unresolved; file not certified clean"
    if counts["CANCELLED"] or status["discovery"] == "CANCELLED":
        return "Checks cancelled; validation required"
    return "Checking / pending" if status["discovery"] != "UNSCANNED" else "Not checked this session"


def refresh(_repository=None):
    global _PROJECTING, _LAST_REFRESH
    if _defer_refresh():
        return
    _PROJECTING = True
    try:
        _project_rows()
        _LAST_REFRESH = perf_counter()
        redraw()
    finally:
        _PROJECTING = False


def _defer_refresh():
    """Repository notifications may arrive before Blender exposes its database."""
    if hasattr(bpy.data, "window_managers"):
        return False
    if not bpy.app.timers.is_registered(_refresh_when_ready):
        bpy.app.timers.register(_refresh_when_ready, first_interval=0.0)
    return True


def _refresh_when_ready():
    if not hasattr(bpy.data, "window_managers"):
        return 0.05
    refresh()


def _project_rows():
    tokens = tuple(warning.id for warning in sorted(REPOSITORY.records.values(), key=sort_key))
    for manager in bpy.data.window_managers:
        _project_manager(manager, tokens)


def _project_manager(manager, tokens):
    current = tuple(row.token for row in manager.af_warning_rows)
    if current == tokens: return
    selected = current[manager.af_warning_index] if 0 <= manager.af_warning_index < len(current) else None
    manager.af_warning_rows.clear()
    for token in tokens: manager.af_warning_rows.add().token = token
    manager.af_warning_index = tokens.index(selected) if selected in tokens else -1


def _cancel_deferred_refresh():
    if bpy.app.timers.is_registered(_refresh_when_ready):
        bpy.app.timers.unregister(_refresh_when_ready)


def redraw():
    for manager in bpy.data.window_managers:
        for window in manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()


@persistent
def clear_projection(_dummy):
    for manager in bpy.data.window_managers:
        manager.af_warning_rows.clear()


@persistent
def restore_projection(_dummy):
    refresh()


def projection_handlers():
    return (("save_pre", clear_projection), ("load_pre", clear_projection),
            ("save_post", restore_projection), ("load_post", restore_projection))


def register():
    global _UNSUBSCRIBE
    if _UNSUBSCRIBE is not None:
        return refresh()
    for cls in (AF_WarningRow, AF_OT_SelectWarning, AF_UL_Warnings):
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.af_warning_rows = bpy.props.CollectionProperty(type=AF_WarningRow, options={"SKIP_SAVE"})
    wm.af_warning_index = bpy.props.IntProperty(default=-1, update=select_index, options={"SKIP_SAVE"})
    wm.af_warnings_expanded = bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    _UNSUBSCRIBE = REPOSITORY.subscribe(request_refresh)
    for name, callback in projection_handlers():
        getattr(bpy.app.handlers, name).append(callback)
    refresh()


def unregister():
    global _UNSUBSCRIBE
    if _UNSUBSCRIBE is not None:
        _UNSUBSCRIBE(); _UNSUBSCRIBE = None
    _cancel_deferred_refresh()
    clear_projection(None)
    for name, callback in projection_handlers():
        group = getattr(bpy.app.handlers, name)
        if callback in group:
            group.remove(callback)
    for name in ("af_warning_rows", "af_warning_index", "af_warnings_expanded"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for cls in (AF_UL_Warnings, AF_OT_SelectWarning, AF_WarningRow):
        bpy.utils.unregister_class(cls)
