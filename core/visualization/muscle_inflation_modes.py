from dataclasses import dataclass
from typing import Protocol

from .muscle_inflation import apply_inflation_distributed, apply_inflation_from_ctrl

CTRL_POINT_MODE = "CTRL_POINT"
DISTRIBUTED_MODE = "DISTRIBUTED"


class MuscleInflationField(Protocol):
    def inflate(self, base_points, muscle): ...


class MuscleInflationControlPolicy(Protocol):
    def uses_control(self): ...
    def ensure_control(self, sync, vis_col, root, muscle, base_obj, base_points): ...
    def cleanup_controls(self, sync, vis_col, root, muscle): ...
    def select_control(self, context, root, vcp, muscle, resolve_ctrl_fn): ...
    def process_control_update(self, sync, root, vis_col, obj, changed_muscle_ids): ...


@dataclass(frozen=True)
class MuscleInflationModeBehavior:
    field: MuscleInflationField
    control: MuscleInflationControlPolicy


class CtrlPointField:
    def inflate(self, base_points, muscle):
        return apply_inflation_from_ctrl(base_points, muscle)


class DistributedField:
    def inflate(self, base_points, muscle):
        return apply_inflation_distributed(base_points, muscle)


class CtrlPointControlPolicy:
    def uses_control(self):
        return True

    def ensure_control(self, sync, vis_col, root, muscle, base_obj, base_points):
        return sync._ensure_inflation_ctrl(vis_col, root, muscle, base_obj, base_points)

    def cleanup_controls(self, sync, vis_col, root, muscle):
        return None

    def select_control(self, context, root, vcp, muscle, resolve_ctrl_fn):
        return resolve_ctrl_fn(context, root, vcp, muscle), ""

    def process_control_update(self, sync, root, vis_col, obj, changed_muscle_ids):
        return sync._process_ctrl_point_update(root, vis_col, obj, changed_muscle_ids)


class NoControlPolicy:
    def uses_control(self):
        return False

    def ensure_control(self, sync, vis_col, root, muscle, base_obj, base_points):
        self.cleanup_controls(sync, vis_col, root, muscle)
        return None

    def cleanup_controls(self, sync, vis_col, root, muscle):
        return sync._remove_inflation_ctrl_for_muscle(vis_col, root.name, muscle.id)

    def select_control(self, context, root, vcp, muscle, resolve_ctrl_fn):
        return None, "Inflation control is only available in CTRL_POINT mode."

    def process_control_update(self, sync, root, vis_col, obj, changed_muscle_ids):
        return False


class SectionProfileField:
    def inflate(self, base_points, muscle):
        from ..vcp.muscle_section_profile import apply_profile, profile_from_muscle
        return apply_profile(base_points, profile_from_muscle(muscle), muscle.inflation_enabled, muscle.flip_normals)


_BEHAVIORS = {
    CTRL_POINT_MODE: MuscleInflationModeBehavior(CtrlPointField(), CtrlPointControlPolicy()),
    DISTRIBUTED_MODE: MuscleInflationModeBehavior(DistributedField(), NoControlPolicy()),
    "SECTION_PROFILE": MuscleInflationModeBehavior(SectionProfileField(), NoControlPolicy()),
}


def muscle_inflation_mode(muscle):
    return str(getattr(muscle, "inflation_mode", CTRL_POINT_MODE))


def muscle_inflation_behavior(muscle):
    mode = muscle_inflation_mode(muscle)
    if mode not in _BEHAVIORS:
        raise ValueError("PROFILE_MODE_UNSUPPORTED: " + mode)
    return _BEHAVIORS[mode]


def uses_inflation_control(muscle):
    return muscle_inflation_mode(muscle) == CTRL_POINT_MODE
