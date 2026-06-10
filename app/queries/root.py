try:
    from ...core.utils import get_af_root
except ImportError:
    from core.utils import get_af_root


def scene_from_context(context):
    return None if context is None else getattr(context, "scene", None)


def root_for_scene(scene):
    return get_af_root(scene)


def root_for_context(context):
    return root_for_scene(scene_from_context(context))


def has_root(context):
    return root_for_context(context) is not None
