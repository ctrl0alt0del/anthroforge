try:
    from ...core.local_transform_props import create_local_transform_props as _create_props
    from ...core.local_transform_props import rebind_local_transform_props as _rebind_props
    from ...core.local_transform_props import remove_local_transform_props as _remove_props
except ImportError:
    from core.local_transform_props import create_local_transform_props as _create_props
    from core.local_transform_props import rebind_local_transform_props as _rebind_props
    from core.local_transform_props import remove_local_transform_props as _remove_props


def create_local_transform_props(context):
    return _create_props(_active_object(context))


def rebind_local_transform_props(context):
    return _rebind_props(_active_object(context))


def remove_local_transform_props(context):
    return _remove_props(_active_object(context))


def _active_object(context):
    return None if context is None else getattr(context, "active_object", None)
