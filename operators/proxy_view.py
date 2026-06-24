import bpy

from ..app.use_cases.proxy_view import exit_proxy_view, switch_to_proxy_view


def _finish(op, context, result):
    if result.ok:
        return {"FINISHED"}
    _popup_lines(context, "Proxy View", result.value) if _can_popup(context, result.value) else None
    op.report({result.level}, result.message)
    return {"CANCELLED"}


def _popup_value(value):
    return isinstance(value, (list, tuple)) and bool(value)


def _can_popup(context, value):
    wm = None if context is None else getattr(context, "window_manager", None)
    return bool(not bpy.app.background and _popup_value(value) and wm and tuple(getattr(wm, "windows", ()) or ()))


def _popup_lines(context, title, lines):
    def draw(menu, _ctx):
        for line in tuple(lines or ()):
            menu.layout.label(text=str(line))

    context.window_manager.popup_menu(draw, title=str(title or "Info"), icon="ERROR")


class AF_OT_SwitchToProxyView(bpy.types.Operator):
    bl_idname = "af.switch_to_proxy_view"
    bl_label = "Switch to Proxy View"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, switch_to_proxy_view(context))


class AF_OT_ExitProxyView(bpy.types.Operator):
    bl_idname = "af.exit_proxy_view"
    bl_label = "Exit Proxy View"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, exit_proxy_view(context))
