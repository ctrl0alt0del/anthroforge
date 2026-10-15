"""Optional checks return unknown evidence on expected execution failures."""
from .draft_skin.status import check_cancelled


def optional(label, callback, cancelled=None):
    check_cancelled(cancelled)
    try:
        return callback()
    except (ValueError, RuntimeError, MemoryError, OSError) as error:
        check_cancelled(cancelled)
        return {"warnings": [f"{label} check failed; quality unknown: {error}"],
                "failed_checks": [label]}


def warm_quality(capture, vertices, faces, progress=None, cancelled=None):
    from .draft_skin.gap_warm import revalidate
    from .mesh_issues import require_mesh
    require_mesh(vertices, faces, 3)
    value = optional("source coverage and gaps", lambda: revalidate(capture, vertices, faces, progress, cancelled), cancelled)
    return (None, value) if isinstance(value, dict) else value


def merge(target, values):
    combined = dict(values)
    for key in ("warnings", "failed_checks"):
        if key in values:
            combined[key] = list(dict.fromkeys((*target.get(key, ()), *values[key])))
    target.update(combined)


def mesh_quality(vertices, faces, covered, cancelled=None):
    from .draft_skin.gap_quality import validate
    value = optional("mesh quality", lambda: validate(vertices, faces, covered), cancelled)
    return (None, value) if isinstance(value, dict) else value
