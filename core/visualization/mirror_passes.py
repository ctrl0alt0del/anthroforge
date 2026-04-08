from .mirror_rules import mirror_world_matrix


def _remove_if_present(sync, obj):
    if obj is not None:
        sync._remove_obj(obj)


def _ensure_mirror(sync, collection, src, existing):
    mir = existing or sync._create_mirror_from_source(collection, src, f"{src.name}_MIR")
    if mir is None:
        return None
    if sync._ensure_obj_type(mir, src) is not None:
        return mir
    sync._remove_obj(mir)
    return sync._create_mirror_from_source(collection, src, f"{src.name}_MIR")


def _copy_mirror_matrix(sync, src, mir, rule):
    sync._copy_data(src, mir)
    axis, origin = rule
    mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)


def _cleanup_mirror_objects(sync, collection, root_name, predicate, key_fn, desired_keys):
    for obj in list(collection.objects):
        if not predicate(obj):
            continue
        if obj.get("af_root_name") != root_name:
            continue
        if key_fn(obj) not in desired_keys:
            sync._remove_obj(obj)


def _scp_intersects_rule_plane(sync, src, rule, explicit):
    axis, origin = explicit if explicit is not None else rule
    return sync._intersects_mirror_plane(src, axis=axis, origin=origin)


def _tag_scp_mirror(sync, mir, root_name, scp_id):
    mir["af_proxy"] = True
    mir["af_mirror_proxy"] = True
    mir["af_root_name"] = root_name
    mir["af_source_scp_id"] = scp_id
    mir["af_scp_id"] = scp_id
    sync._ensure_mirror_material(mir, alpha_mult=0.60)


def _tag_fiber_mirror(sync, mir, root_name, fiber_id):
    mir["af_fiber_proxy"] = True
    mir["af_fiber_mirror_proxy"] = True
    mir["af_root_name"] = root_name
    mir["af_source_fiber_id"] = fiber_id
    mir["af_fiber_id"] = fiber_id
    sync._ensure_mirror_material(mir, alpha_mult=0.65)


def _tag_muscle_mirror(sync, mir, root_name, muscle_id, surf):
    mir["af_muscle_proxy"] = True
    mir["af_muscle_mirror_proxy"] = True
    mir["af_root_name"] = root_name
    mir["af_source_muscle_id"] = muscle_id
    mir["af_muscle_id"] = muscle_id
    mir["af_muscle_surface"] = surf
    sync._ensure_mirror_material(mir, alpha_mult=0.60)


def _sync_one_scp_mirror(sync, root, scp_col, scp_id, scp_prop, scp_map):
    rule = sync._effective_rule_for_scp(scp_id, scp_map)
    src = sync._find_source_scp_obj(scp_col, root.name, scp_id)
    mir = sync._find_mirror_scp_obj(scp_col, root.name, scp_id)
    if rule is None or src is None:
        _remove_if_present(sync, mir)
        return False
    explicit = sync._explicit_mirror_rule_for_scp(scp_prop)
    if _scp_intersects_rule_plane(sync, src, rule, explicit):
        _remove_if_present(sync, mir)
        return False
    mir = _ensure_mirror(sync, scp_col, src, mir)
    if mir is None:
        return False
    _copy_mirror_matrix(sync, src, mir, rule)
    _tag_scp_mirror(sync, mir, root.name, scp_id)
    return True


def _sync_one_fiber_mirror(sync, root, vcp_col, fiber, scp_map):
    rule = sync._effective_rule_for_fiber(fiber, scp_map)
    src = sync._find_source_fiber_obj(vcp_col, root.name, fiber.id)
    mir = sync._find_mirror_fiber_obj(vcp_col, root.name, fiber.id)
    if rule is None or src is None:
        _remove_if_present(sync, mir)
        return False
    mir = _ensure_mirror(sync, vcp_col, src, mir)
    if mir is None:
        return False
    _copy_mirror_matrix(sync, src, mir, rule)
    _tag_fiber_mirror(sync, mir, root.name, fiber.id)
    return True


def _sync_one_muscle_mirror(sync, root, vcp_col, muscle, surf, rule):
    src = sync._find_source_muscle_obj(vcp_col, root.name, muscle.id, surf)
    mir = sync._find_mirror_muscle_obj(vcp_col, root.name, muscle.id, surf)
    if rule is None or src is None:
        _remove_if_present(sync, mir)
        return False
    mir = _ensure_mirror(sync, vcp_col, src, mir)
    if mir is None:
        return False
    _copy_mirror_matrix(sync, src, mir, rule)
    _tag_muscle_mirror(sync, mir, root.name, muscle.id, surf)
    return True


def sync_scp_mirrors(sync, root, scene, scp_col, scp_map):
    if scp_col is None:
        return

    desired_ids = set()
    for scp_id, scp_prop in scp_map.items():
        if _sync_one_scp_mirror(sync, root, scp_col, scp_id, scp_prop, scp_map):
            desired_ids.add(scp_id)
    _cleanup_mirror_objects(
        sync,
        scp_col,
        root.name,
        lambda o: o.get("af_proxy") and o.get("af_mirror_proxy"),
        lambda o: o.get("af_source_scp_id"),
        desired_ids,
    )


def sync_fiber_mirrors(sync, root, vcp_col, scp_map, fibers_by_id):
    if vcp_col is None:
        return

    desired_ids = set()
    for fiber in root.af_vcp_system.fibers:
        if _sync_one_fiber_mirror(sync, root, vcp_col, fiber, scp_map):
            desired_ids.add(fiber.id)
    _cleanup_mirror_objects(
        sync,
        vcp_col,
        root.name,
        lambda o: o.get("af_fiber_proxy") and o.get("af_fiber_mirror_proxy"),
        lambda o: o.get("af_source_fiber_id"),
        desired_ids,
    )


def sync_muscle_mirrors(sync, root, vcp_col, scp_map, fibers_by_id):
    if vcp_col is None:
        return

    desired_keys = set()
    for muscle in root.af_vcp_system.muscles:
        rule = sync._effective_rule_for_muscle(muscle, fibers_by_id, scp_map)
        for surf in ("BASE", "INFL"):
            if _sync_one_muscle_mirror(sync, root, vcp_col, muscle, surf, rule):
                desired_keys.add((muscle.id, surf))
    _cleanup_mirror_objects(
        sync,
        vcp_col,
        root.name,
        lambda o: o.get("af_muscle_proxy") and o.get("af_muscle_mirror_proxy"),
        lambda o: (o.get("af_source_muscle_id"), o.get("af_muscle_surface")),
        desired_keys,
    )
