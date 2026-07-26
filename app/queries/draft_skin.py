from dataclasses import dataclass

from .root import has_root


@dataclass(frozen=True)
class DraftSkinPanelState:
    has_root: bool
    running: bool
    stage: str
    progress: float
    message: str
    diagnostic: str


def draft_skin_panel_state(context):
    scene = context.scene
    return DraftSkinPanelState(
        has_root(context),
        bool(getattr(scene, "af_draft_skin_running", False)),
        str(getattr(scene, "af_draft_skin_stage", "") or ""),
        float(getattr(scene, "af_draft_skin_progress", 0.0)),
        str(getattr(scene, "af_draft_skin_message", "") or ""),
        str(getattr(scene, "af_draft_skin_diagnostic", "") or ""),
    )
