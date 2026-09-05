"""Live VCP ownership and object hiding in one explicitly supplied view layer."""

from dataclasses import dataclass


CATEGORY_ROLES = {
    "MUSCLE": ("muscles", ("af_muscle_proxy", "af_muscle_inflation_ctrl")),
    "FIBER": ("fibers", ("af_fiber_proxy", "af_fiber_endpoint_handle",
                         "af_fiber_touch_handle", "af_fiber_loop_anchor_handle")),
}
_VISIBILITY_ERRORS = (ReferenceError, RuntimeError, TypeError)


@dataclass(frozen=True)
class CategoryVisibility:
    unhidden: int = 0
    hidden: int = 0
    unavailable: int = 0
    changed: int = 0

    @property
    def available(self):
        return self.unhidden + self.hidden

    @property
    def status(self):
        if not self.available:
            return "Unavailable" if self.unavailable else "No objects"
        if self.hidden and self.unhidden:
            return "Mixed"
        return "All hidden" if self.hidden else "All unhidden"


def category_objects(scene, root, category):
    if root is None or category not in CATEGORY_ROLES:
        return ()
    collection, roles = CATEGORY_ROLES[category]
    system = getattr(root, "af_vcp_system", None)
    live_ids = {str(row.id) for row in getattr(system, collection, ()) if row.id}
    return tuple(obj for obj in getattr(scene, "objects", ())
                 if _owned(obj, root.name, category, roles, live_ids))


def _owned(obj, root_name, category, roles, live_ids):
    try:
        if obj.get("af_root_name") != root_name or not any(obj.get(role) for role in roles):
            return False
        kind = category.lower()
        owner = obj.get(f"af_{kind}_id")
        if obj.get(f"af_{kind}_mirror_proxy"):
            owner = obj.get(f"af_source_{kind}_id") or owner
        return str(owner or "") in live_ids
    except _VISIBILITY_ERRORS:
        return False


def object_hidden(obj, view_layer):
    try:
        if view_layer is None or view_layer.objects.get(obj.name) != obj:
            return None
        return bool(obj.hide_get(view_layer=view_layer))
    except _VISIBILITY_ERRORS:
        return None


def category_visibility(scene, view_layer, root, category):
    states = [object_hidden(obj, view_layer) for obj in category_objects(scene, root, category)]
    return _summary(states)


def _summary(states, changed=0):
    return CategoryVisibility(states.count(False), states.count(True), states.count(None), changed)


def set_category_visibility(scene, view_layer, root, category, hidden):
    states, changed = [], 0
    for obj in category_objects(scene, root, category):
        state = object_hidden(obj, view_layer)
        if state is not None and state != bool(hidden):
            state = _set_hidden(obj, view_layer, hidden)
            changed += state is not None and state == bool(hidden)
        states.append(state)
    return _summary(states, changed)


def _set_hidden(obj, view_layer, hidden):
    try:
        obj.hide_set(bool(hidden), view_layer=view_layer)
        return object_hidden(obj, view_layer)
    except _VISIBILITY_ERRORS:
        return None


def fiber_proxy_visible(scene, view_layer, root, fiber_id, viewport=None):
    for obj in category_objects(scene, root, "FIBER"):
        if _source_proxy(obj, fiber_id) and _effectively_visible(obj, view_layer, viewport):
            return True
    return False


def _source_proxy(obj, fiber_id):
    return (obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy")
            and str(obj.get("af_fiber_id", "")) == str(fiber_id))


def _effectively_visible(obj, view_layer, viewport):
    if object_hidden(obj, view_layer) is not False:
        return False
    try:
        return bool(obj.visible_get(view_layer=view_layer, viewport=viewport))
    except _VISIBILITY_ERRORS:
        return False
