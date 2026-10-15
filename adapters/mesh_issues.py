"""Blender publication, persisted diagnostics and generic issue-system adapter."""
import json
from uuid import uuid4
import bpy
try:
    from ..core.mesh_issues import annotate, finding, require_mesh, restore_report
    from ..core.mesh_diagnostics import check_result
    from ..core.issues.model import EntityReference, Issue
    from ..core.warnings import session
except ImportError:
    from core.mesh_issues import annotate, finding, require_mesh, restore_report
    from core.mesh_diagnostics import check_result
    from core.issues.model import EntityReference, Issue
    from core.warnings import session

PROVIDER = "mesh_pipeline.v1"


def persist(obj, result, stage):
    annotate(result, stage)
    revision = uuid4().hex
    payload = dict(version=1, revision=revision, stage=stage, issues=result.statistics["issues"],
                   quality=result.statistics.get("quality_report"), log=result.statistics.get("diagnostic_path", ""))
    obj["af_issues_json"] = json.dumps(payload, sort_keys=True)
    obj.data["af_artifact_revision"] = revision
    obj.data["af_result_stats_json"] = json.dumps(result.statistics, sort_keys=True)


def publish(obj, scene, root, stale=False):
    payload = _payload(obj)
    ref = _reference(obj, scene, root)
    rows = tuple(_issue(ref, row, payload) for row in payload.get("issues", ()))
    check = session.SYSTEM.reporting.begin_check(ref.scope, PROVIDER)
    session.SYSTEM.reporting.complete_check(check, rows, payload)
    if stale:
        session.REPOSITORY.state(ref.scope, "UNSCANNED", provider=PROVIDER)


def _reference(obj, scene, root):
    return EntityReference(session.EPOCH, session.id_token(scene), session.id_token(root),
                           "ARTIFACT", session.id_token(obj), 0, obj.name, scene.name, root.name)


def _issue(ref, row, payload):
    return Issue(ref, row["code"], row["summary"], row.get("details", ""),
                 tuple(dict(row.get("evidence", {}), log=payload.get("log", "")).items()), PROVIDER, row.get("stage", payload["stage"]),
                 payload.get("revision", ""), row.get("local_key", row["code"]), row.get("severity", "warning"))


def _payload(obj):
    try:
        return json.loads(obj["af_issues_json"])
    except (KeyError, TypeError, ValueError):
        return dict(stage="restored", issues=[finding("QUALITY_UNKNOWN", "Saved output has no verified diagnostics", "restored")])


def retain_reference(scene, root, previous_mesh):
    topology = next((o for o in scene.objects if o.get("af_topology") and o.get("af_root_name") == root.name), None)
    if topology is None or previous_mesh is None:
        return
    if topology.get("af_bound_skin") is None:
        topology["af_bound_skin"] = previous_mesh
        previous_mesh['af_owned_binding_reference'] = True
    topology["af_topology_stale"] = True
    payload = _payload(topology)
    payload["issues"] = [r for r in payload["issues"] if r["code"] != "TOPOLOGY_STALE"]
    payload["issues"].append(finding("TOPOLOGY_STALE", "Topology still uses the previous skin; update required", "topology"))
    topology["af_issues_json"] = json.dumps(payload)
    publish(topology, scene, root, stale=True)


def bind_reference(scene, root, topology):
    skin = next((o for o in scene.objects if o.get("af_draft_skin") and o.get("af_root_name") == root.name), None)
    previous = topology.get("af_bound_skin")
    if skin is not None:
        topology["af_bound_skin"] = skin.data
    topology["af_topology_stale"] = False
    if previous is not None and not previous.users and previous.get('af_owned_binding_reference'):
        bpy.data.meshes.remove(previous)


def select(issue, context):
    from ..core.visualization.warning_selection import select_object
    if issue.entity.epoch != session.EPOCH or context.window is None:
        return False
    scene = next((s for s in bpy.data.scenes if session.id_token(s) == issue.entity.scene), None)
    obj = None if scene is None else next((o for o in scene.objects if session.id_token(o) == issue.entity.native_id), None)
    if obj is None:
        return False
    context.window.scene = scene
    return select_object(context.window.view_layer, obj)


class ArtifactListener:
    name = PROVIDER

    def check_all(self, context):
        for scene in bpy.data.scenes:
            for obj in scene.objects:
                if obj.get("af_draft_skin") or obj.get("af_topology"):
                    root = scene.objects.get(obj.get("af_root_name", ""))
                    if root is not None:
                        if context is None:
                            publish(obj, scene, root, stale=True)
                        else:
                            from .issue_recheck import schedule
                            schedule(obj, scene, root)

    def on_action(self, event, context):
        if event.get("event_type") == "SELECTION":
            return
        scene, root = context
        if scene is not None and root is not None:
            _restore_missing(scene, root)
        for scope, provider in tuple(session.REPOSITORY.provider_states):
            if provider == self.name and (root is None or scope[2] == session.id_token(root)):
                session.SYSTEM.reporting.invalidate(scope, self.name)


def _restore_missing(scene, root):
    for obj in scene.objects:
        if obj.get('af_root_name') == root.name and (obj.get('af_draft_skin') or obj.get('af_topology')):
            scope = _reference(obj, scene, root).scope
            if (scope, PROVIDER) not in session.REPOSITORY.provider_states:
                publish(obj, scene, root, stale=True)


def publish_summary(scene, root, summary):
    if summary.get("state") != "PARTIAL":
        return
    targets = [o for o in scene.objects if o.get("af_root_name") == root.name and o.get("af_topology")]
    if not targets:
        targets = [o for o in scene.objects if o.get("af_root_name") == root.name and o.get("af_draft_skin")]
    for obj in targets:
        payload = _payload(obj)
        payload["issues"].extend(summary.get("issues", ()))
        obj["af_issues_json"] = json.dumps(payload)
        publish(obj, scene, root, stale=True)
