"""Reject stale asynchronous publication after edits, undo, load, or root replacement."""
try:
    from ..core.warnings import session
except ImportError:
    from core.warnings import session


def stamp(scene, root_name):
    root = getattr(scene, "objects", {}).get(root_name)
    identity = "" if root is None else session.id_token(root)
    return session.EPOCH, session.id_token(scene), identity, session.CHANGES.get(identity, 0)


def attach(job, scene):
    job.issue_revision = stamp(scene, job.spec.root_name)


def require_current(job, scene):
    from pathlib import Path
    if Path(job.spec.cancel_path).exists():
        raise RuntimeError("Generation was cancelled; completed files remain available for diagnosis.")
    if getattr(job, "issue_revision", None) != stamp(scene, job.spec.root_name):
        raise RuntimeError("The source changed during generation; previous output retained. Generate again.")
