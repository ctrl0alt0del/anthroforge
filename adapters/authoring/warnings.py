"""Live warning feedback is added outside persistent authoring receipts."""
from ...core.warnings.query import WarningQuery
from ...core.warnings.session import id_token

MUTATIONS = {"build", "patch", "resume", "publish_draft", "anatomy.initialize",
             "anatomy.publish", "anatomy.reconcile", "anatomy.recover", "anatomy.adopt_binding"}


class BlenderWarnings(WarningQuery):
    def __init__(self, root, scene):
        self.root, self.scene = root, scene

    def feedback(self, request, result, replayed=False):
        if request.get("op") == "warnings.list":
            return dict(result)
        from ...core.visualization.warning_runtime import notify_action, structural_change
        if request.get("op") in MUTATIONS and not replayed and not result.get("replayed"):
            structural_change(self.root)
            notify_action(self.root, self.scene, full=True, event_type="AUTHORING")
        params = dict(scene=id_token(self.scene), root=id_token(self.root), limit=0)
        return dict(result, warnings=self.list(params))
