from dataclasses import dataclass, field

from .root import root_for_context, scene_from_context
from .scp import active_scp_id

try:
    from ...core.scp_runtime.visibility import isolated_scp_id
    from ...core.visualization.category_visibility import CategoryVisibility, category_visibility
except ImportError:
    from core.scp_runtime.visibility import isolated_scp_id
    from core.visualization.category_visibility import CategoryVisibility, category_visibility


@dataclass(frozen=True)
class TreeSelection:
    scp_ids: frozenset = field(default_factory=frozenset)
    fiber_ids: frozenset = field(default_factory=frozenset)
    fiber_surface_ids: frozenset = field(default_factory=frozenset)
    muscle_ids: frozenset = field(default_factory=frozenset)
    blob_ids: frozenset = field(default_factory=frozenset)
    soft_tissue_ids: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class TreePanelState:
    scene: object = None
    root: object = None
    active_scp_id: str = ""
    isolated_scp_id: str = ""
    selection: TreeSelection = field(default_factory=TreeSelection)
    muscle_visibility: CategoryVisibility = field(default_factory=CategoryVisibility)
    fiber_visibility: CategoryVisibility = field(default_factory=CategoryVisibility)


def _selected_objects(context):
    return tuple(() if context is None else getattr(context, "selected_objects", ()) or ())


def _matches_root(obj, root):
    return obj.get("af_root_name") == root.name


def selected_scp_ids(context, root):
    out = set()
    for obj in _selected_objects(context):
        if obj.get("af_scp_bound") and not obj.get("af_scp_mirror") and _matches_root(obj, root) and obj.get("af_scp_id"):
            out.add(obj.get("af_scp_id"))
    return out


def _collect_selected_id(obj, root, flag, id_key, out):
    if _matches_root(obj, root) and obj.get(flag) and obj.get(id_key):
        out.add(obj.get(id_key))


def selected_vcp_ids(context, root):
    fibers, muscles, blobs = set(), set(), set()
    for obj in _selected_objects(context):
        _collect_selected_id(obj, root, "af_fiber_proxy", "af_fiber_id", fibers)
        _collect_selected_id(obj, root, "af_muscle_proxy", "af_muscle_id", muscles)
        _collect_selected_id(obj, root, "af_blob_proxy", "af_blob_id", blobs)
    return fibers, muscles, blobs


def selected_fiber_surface_ids(context, root):
    surfaces = set()
    for obj in _selected_objects(context):
        _collect_selected_id(obj, root, "af_fiber_surface_proxy", "af_fiber_surface_id", surfaces)
    return surfaces


def _tree_selection(context, root):
    fibers, muscles, blobs = selected_vcp_ids(context, root)
    soft = set()
    for obj in _selected_objects(context):
        _collect_selected_id(obj, root, "af_soft_tissue_proxy", "af_soft_tissue_id", soft)
        _collect_selected_id(obj, root, "af_soft_tissue_rest_proxy", "af_soft_tissue_id", soft)
        _collect_selected_id(obj, root, "af_soft_tissue_base", "af_soft_tissue_id", soft)
    return TreeSelection(
        scp_ids=frozenset(selected_scp_ids(context, root)),
        fiber_ids=frozenset(fibers),
        fiber_surface_ids=frozenset(selected_fiber_surface_ids(context, root)),
        muscle_ids=frozenset(muscles),
        blob_ids=frozenset(blobs),
        soft_tissue_ids=frozenset(soft),
    )


def tree_panel_state(context):
    scene = scene_from_context(context)
    root = root_for_context(context)
    if root is None:
        return TreePanelState(scene=scene)
    isolated = isolated_scp_id(scene, getattr(context, "view_layer", None), root.name)
    layer = getattr(context, "view_layer", None)
    return TreePanelState(scene=scene, root=root, active_scp_id=active_scp_id(context),
                         isolated_scp_id=isolated, selection=_tree_selection(context, root),
                         muscle_visibility=category_visibility(scene, layer, root, "MUSCLE"),
                         fiber_visibility=category_visibility(scene, layer, root, "FIBER"))
