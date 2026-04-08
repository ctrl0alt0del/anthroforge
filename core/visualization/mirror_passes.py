from .mirror_rules import mirror_world_matrix


def sync_scp_mirrors(sync, root, scene, scp_col, scp_map):
    if scp_col is None:
        return

    desired_ids = set()
    for scp_id, scp_prop in scp_map.items():
        rule = sync._effective_rule_for_scp(scp_id, scp_map)
        src = sync._find_source_scp_obj(scp_col, root.name, scp_id)
        mir = sync._find_mirror_scp_obj(scp_col, root.name, scp_id)

        if rule is None or src is None:
            if mir is not None:
                sync._remove_obj(mir)
            continue

        explicit = sync._explicit_mirror_rule_for_scp(scp_prop)
        if explicit is not None:
            axis_e, origin_e = explicit
            if sync._intersects_mirror_plane(src, axis=axis_e, origin=origin_e):
                if mir is not None:
                    sync._remove_obj(mir)
                continue
        else:
            axis_i, origin_i = rule
            if sync._intersects_mirror_plane(src, axis=axis_i, origin=origin_i):
                if mir is not None:
                    sync._remove_obj(mir)
                continue

        if mir is None:
            mir = sync._create_mirror_from_source(scp_col, src, f"{src.name}_MIR")
        if mir is None:
            continue

        if sync._ensure_obj_type(mir, src) is None:
            sync._remove_obj(mir)
            mir = sync._create_mirror_from_source(scp_col, src, f"{src.name}_MIR")
            if mir is None:
                continue

        sync._copy_data(src, mir)
        axis, origin = rule
        mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)

        mir["af_proxy"] = True
        mir["af_mirror_proxy"] = True
        mir["af_root_name"] = root.name
        mir["af_source_scp_id"] = scp_id
        mir["af_scp_id"] = scp_id
        sync._ensure_mirror_material(mir, alpha_mult=0.60)
        desired_ids.add(scp_id)

    for obj in list(scp_col.objects):
        if not obj.get("af_proxy"):
            continue
        if not obj.get("af_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        sid = obj.get("af_source_scp_id")
        if sid not in desired_ids:
            sync._remove_obj(obj)


def sync_fiber_mirrors(sync, root, vcp_col, scp_map, fibers_by_id):
    if vcp_col is None:
        return

    desired_ids = set()
    for fiber in root.af_vcp_system.fibers:
        rule = sync._effective_rule_for_fiber(fiber, scp_map)
        src = sync._find_source_fiber_obj(vcp_col, root.name, fiber.id)
        mir = sync._find_mirror_fiber_obj(vcp_col, root.name, fiber.id)

        if rule is None or src is None:
            if mir is not None:
                sync._remove_obj(mir)
            continue

        if mir is None:
            mir = sync._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
        if mir is None:
            continue

        if sync._ensure_obj_type(mir, src) is None:
            sync._remove_obj(mir)
            mir = sync._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
            if mir is None:
                continue

        sync._copy_data(src, mir)
        axis, origin = rule
        mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)

        mir["af_fiber_proxy"] = True
        mir["af_fiber_mirror_proxy"] = True
        mir["af_root_name"] = root.name
        mir["af_source_fiber_id"] = fiber.id
        mir["af_fiber_id"] = fiber.id
        sync._ensure_mirror_material(mir, alpha_mult=0.65)
        desired_ids.add(fiber.id)

    for obj in list(vcp_col.objects):
        if not obj.get("af_fiber_proxy"):
            continue
        if not obj.get("af_fiber_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        fid = obj.get("af_source_fiber_id")
        if fid not in desired_ids:
            sync._remove_obj(obj)


def sync_muscle_mirrors(sync, root, vcp_col, scp_map, fibers_by_id):
    if vcp_col is None:
        return

    desired_keys = set()
    for muscle in root.af_vcp_system.muscles:
        rule = sync._effective_rule_for_muscle(muscle, fibers_by_id, scp_map)

        for surf in ("BASE", "INFL"):
            src = sync._find_source_muscle_obj(vcp_col, root.name, muscle.id, surf)
            mir = sync._find_mirror_muscle_obj(vcp_col, root.name, muscle.id, surf)

            if rule is None or src is None:
                if mir is not None:
                    sync._remove_obj(mir)
                continue

            if mir is None:
                mir = sync._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
            if mir is None:
                continue

            if sync._ensure_obj_type(mir, src) is None:
                sync._remove_obj(mir)
                mir = sync._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
                if mir is None:
                    continue

            sync._copy_data(src, mir)
            axis, origin = rule
            mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)

            mir["af_muscle_proxy"] = True
            mir["af_muscle_mirror_proxy"] = True
            mir["af_root_name"] = root.name
            mir["af_source_muscle_id"] = muscle.id
            mir["af_muscle_id"] = muscle.id
            mir["af_muscle_surface"] = surf
            sync._ensure_mirror_material(mir, alpha_mult=0.60)
            desired_keys.add((muscle.id, surf))

    for obj in list(vcp_col.objects):
        if not obj.get("af_muscle_proxy"):
            continue
        if not obj.get("af_muscle_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        key = (obj.get("af_source_muscle_id"), obj.get("af_muscle_surface"))
        if key not in desired_keys:
            sync._remove_obj(obj)
