import bpy


def get_af_root(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None

    for obj in scene.objects:
        if obj.get("anthroforge_root"):
            return obj
    return None


def create_af_root(scene):
    root = bpy.data.objects.new("AF_ROOT", None)
    scene.collection.objects.link(root)
    root.empty_display_type, root.empty_display_size = "PLAIN_AXES", 0.5
    root["anthroforge_root"] = True
    root.af_scp_system, root.af_vcp_system, root.af_shortcut_system
    return root


def ensure_af_root(scene):
    return get_af_root(scene) or create_af_root(scene)
