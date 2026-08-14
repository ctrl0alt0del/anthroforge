from bpy_extras import view3d_utils


NO_VIEW_RAY = object()


def view_ray_for_world_point(world_point, context=None):
    state = None if context is None else _view_state(context)
    return NO_VIEW_RAY if state is None else _ray_from_state(world_point, *state)


def _view_state(context):
    direct = _direct_state(context)
    return direct if direct is not None else _largest_view_state(context)


def _direct_state(context):
    area, region = getattr(context, "area", None), getattr(context, "region", None)
    space = getattr(context, "space_data", None)
    valid = getattr(area, "type", "") == "VIEW_3D" and getattr(region, "type", "") == "WINDOW"
    rv3d = getattr(space, "region_3d", None)
    return (region, rv3d) if valid and rv3d is not None else None


def _largest_view_state(context):
    screen = getattr(context, "screen", None)
    states = [_area_state(area) for area in tuple(getattr(screen, "areas", ()) or ())]
    present = [state for state in states if state is not None]
    return None if not present else max(present, key=_state_area)


def _area_state(area):
    if getattr(area, "type", "") != "VIEW_3D":
        return None
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    rv3d = getattr(getattr(area.spaces, "active", None), "region_3d", None)
    return (region, rv3d) if region is not None and rv3d is not None else None


def _state_area(state):
    region = state[0]
    return int(getattr(region, "width", 0)) * int(getattr(region, "height", 0))


def _ray_from_state(world_point, region, rv3d):
    coord = view3d_utils.location_3d_to_region_2d(region, rv3d, world_point, default=None)
    if coord is None:
        return None
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord, clamp=_ray_clamp(world_point, rv3d))
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord).normalized()
    return origin.copy(), direction.copy()


def _ray_clamp(world_point, rv3d):
    location = getattr(rv3d, "view_location", world_point)
    return max(1.0, float((world_point - location).length) * 4.0)
