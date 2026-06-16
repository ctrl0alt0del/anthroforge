def mirror_target_worlds(clones, mirror_mat):
    return {clone: mirror_mat @ source.matrix_world for source, clone in clones.items()}


def mirror_clone_pairs(clones):
    return tuple(sorted(clones.items(), key=lambda item: _source_depth(item[0])))


def _source_depth(obj):
    depth, cur = 0, getattr(obj, "parent", None)
    while cur is not None:
        depth, cur = depth + 1, cur.parent
    return depth


def mirror_parent_for(source_obj, clones, target_world, eps=1e-5):
    parent = clones.get(getattr(source_obj, "parent", None))
    if parent is None:
        return None
    return None if mirror_has_shear(_local_target(parent, target_world), eps=eps) else parent


def _local_target(parent, target_world):
    return parent.matrix_world.inverted_safe() @ target_world


def mirror_has_shear(matrix, eps=1e-5):
    cols = tuple(_normalized_col(matrix.to_3x3().col[i].copy()) for i in range(3))
    dots = (abs(cols[a].dot(cols[b])) for a, b in ((0, 1), (0, 2), (1, 2)))
    return any(dot > eps for dot in dots)


def _normalized_col(col):
    return col if col.length <= 1e-8 else col.normalized()


def apply_parent_target(obj, parent, target_world):
    obj.parent = parent
    obj.matrix_parent_inverse.identity()
    obj.matrix_basis = _local_target(parent, target_world)
