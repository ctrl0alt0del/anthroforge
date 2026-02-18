import bpy


def get_af_root(scene=None):
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None

    for obj in scene.objects:
        if obj.get("anthroforge_root"):
            return obj
    return None
