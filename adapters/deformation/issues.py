"""Execution problems are reported through the shared issue facade."""
from ..mesh_issues import _reference
from ...core.issues.model import Issue
from ...core.issues.api import report as publish


def report(scene, root, message):
    ref = _reference(root,scene,root)
    publish(Issue(ref,"DEFORMATION_UNAVAILABLE",message,
        "Previous output was preserved. Resolve the problem and use Update Now or explicitly initialize again.",
        (),"deformation.v1","update","","execution","warning"))
