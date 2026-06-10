from dataclasses import dataclass

from .root import root_for_context, scene_from_context
from .scp import active_scp_from_context


@dataclass(frozen=True)
class CreatePanelState:
    scene: object = None
    root: object = None
    active_scp: object = None


def create_panel_state(context):
    return CreatePanelState(
        scene=scene_from_context(context),
        root=root_for_context(context),
        active_scp=active_scp_from_context(context),
    )
