from dataclasses import dataclass

from .root import root_for_context


@dataclass(frozen=True)
class TopologyPanelState:
    has_root: bool
    has_skin: bool
    running: bool
    stage: str
    progress: float
    message: str
    diagnostic: str


def topology_panel_state(context):
    scene, root = context.scene, root_for_context(context)
    skin = root is not None and any(obj.get("af_draft_skin")
                                    and obj.get("af_root_name") == root.name
                                    for obj in scene.objects)
    return TopologyPanelState(
        root is not None, bool(skin), bool(getattr(scene, "af_topology_running", False)),
        str(getattr(scene, "af_topology_stage", "") or ""),
        float(getattr(scene, "af_topology_progress", 0.0)),
        str(getattr(scene, "af_topology_message", "") or ""),
        str(getattr(scene, "af_topology_diagnostic", "") or ""))
