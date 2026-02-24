import bpy

from ..core.utils import get_af_root
from ..core.visualization.fiber_sync import register_fiber_sync
from ..core.visualization.muscle_sync import register_muscle_sync


def _selected_fiber_ids(context, root):
    ids = []
    seen = set()

    # Put active fiber first if selected
    active = context.active_object
    if (
        active
        and active.get("af_fiber_proxy")
        and active.get("af_root_name") == root.name
        and active.get("af_fiber_id")
        and active.select_get()
    ):
        fid = active.get("af_fiber_id")
        ids.append(fid)
        seen.add(fid)

    # Then all other selected fibers
    for obj in context.selected_objects:
        if not obj.get("af_fiber_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        fid = obj.get("af_fiber_id")
        if not fid or fid in seen:
            continue
        ids.append(fid)
        seen.add(fid)

    return ids


class AF_OT_AddMuscleVCP(bpy.types.Operator):
    bl_idname = "af.add_muscle_vcp"
    bl_label = "Create Muscle From Selected Fibers"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", default="")
    closed_v: bpy.props.BoolProperty(name="Closed Ring (V)", default=False)

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({"ERROR"}, "No AF_ROOT found.")
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        fiber_ids = _selected_fiber_ids(context, root)

        if len(fiber_ids) < 2:
            self.report({"ERROR"}, "Select at least 2 fiber proxies in viewport (Shift-select).")
            return {"CANCELLED"}

        # Validate all selected fibers exist and have identical node_count / anchor structure
        fibers_by_id = {f.id: f for f in vcp.fibers}
        fibers = []
        for fid in fiber_ids:
            f = fibers_by_id.get(fid)
            if f is None:
                self.report({"ERROR"}, f"Fiber '{fid}' not found.")
                return {"CANCELLED"}
            fibers.append(f)

        node_count = int(fibers[0].node_count)
        anchor_count = len(fibers[0].mid_touches)
        for f in fibers[1:]:
            if int(f.node_count) != node_count:
                self.report({"ERROR"}, "Selected fibers must have identical node_count.")
                return {"CANCELLED"}
            if len(f.mid_touches) != anchor_count:
                self.report({"ERROR"}, "Selected fibers must have identical anchor structure.")
                return {"CANCELLED"}

        # Create unique muscle ID
        existing_ids = {m.id for m in vcp.muscles}
        i = 1
        muscle_id = f"MUSCLE_{i}"
        while muscle_id in existing_ids:
            i += 1
            muscle_id = f"MUSCLE_{i}"

        m = vcp.muscles.add()
        m.id = muscle_id
        m.name = self.name.strip() if self.name.strip() else muscle_id
        m.closed_v = bool(self.closed_v)

        # Remove these fibers from previous muscle refs, then assign to new muscle in selected order
        for fid in fiber_ids:
            for old_m in vcp.muscles:
                if old_m.id == muscle_id:
                    continue
                rm = [idx for idx, ref in enumerate(old_m.fiber_refs) if ref.fiber_id == fid]
                for idx in reversed(rm):
                    old_m.fiber_refs.remove(idx)

            ref = m.fiber_refs.add()
            ref.fiber_id = fid
            fibers_by_id[fid].muscle_id = muscle_id

        m.active_fiber_ref_index = 0 if len(m.fiber_refs) > 0 else -1

        vcp.active_vcp_type = "MUSCLE"
        vcp.active_vcp_id = muscle_id

        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        register_muscle_sync().sync_root_to_scene(root=root, scene=context.scene)

        self.report({"INFO"}, f"Created {muscle_id} from {len(fiber_ids)} fibers")
        return {"FINISHED"}
