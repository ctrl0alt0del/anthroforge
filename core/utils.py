import bpy


def get_af_root(scene=None):
    if scene is None:
        return None

    for obj in scene.objects:
        if obj.get("anthroforge_root"):
            return obj
    return None


def scene_for_id(owner):
    scenes = tuple(getattr(owner, "users_scene", ()) or ())
    return scenes[0] if scenes else None


def view_layer_for_scene(scene):
    layers = tuple(getattr(scene, "view_layers", ()) or ())
    return None if scene is None or not layers else layers[0]


def depsgraph_for_scene(scene):
    layer = view_layer_for_scene(scene)
    update_scene_view_layer(scene)
    return None if layer is None else getattr(layer, "depsgraph", None)


def update_scene_view_layer(scene):
    try:
        None if scene is None else view_layer_for_scene(scene).update()
    except Exception:
        return


def create_af_root(scene):
    root = bpy.data.objects.new("AF_ROOT", None)
    scene.collection.objects.link(root)
    root.empty_display_type, root.empty_display_size = "PLAIN_AXES", 0.5
    root["anthroforge_root"] = True
    root.af_scp_system, root.af_vcp_system, root.af_shortcut_system
    return root


def ensure_af_root(scene):
    return get_af_root(scene) or create_af_root(scene)
