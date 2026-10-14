"""Generic issue actions and details; no diagnostic or repair work in draw."""
import json
import bpy
from ..core.warnings.session import SYSTEM, REPOSITORY


class AF_OT_IssueAction(bpy.types.Operator):
    bl_idname = "af.issue_action"
    bl_label = "Issue action"
    token: bpy.props.StringProperty(options={"SKIP_SAVE"})
    action: bpy.props.StringProperty(options={"SKIP_SAVE"})
    solver: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        try:
            execute(self.action, self.token, self.solver, context)
        except (KeyError, ValueError, RuntimeError) as error:
            self.report({"WARNING"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def execute(action, token, solver, context):
    row = REPOSITORY.records[token]
    if action == "DISMISS":
        SYSTEM.presentation.dismiss(token)
    elif action == "RECHECK":
        SYSTEM.listening.recheck(row.provider, context)
    elif action == "FIX":
        SYSTEM.resolution.invoke(token, solver, context)
    elif action == "CANCEL":
        SYSTEM.resolution.cancel(token, context)


def draw(layout, context):
    manager = context.window_manager
    if not 0 <= manager.af_warning_index < len(manager.af_warning_rows):
        return
    issue = REPOSITORY.records.get(manager.af_warning_rows[manager.af_warning_index].token)
    if issue is None:
        return
    value = SYSTEM.presentation.serialize(issue)
    layout.label(text=f"{issue.provider} / {getattr(issue, 'stage', '')} / {value['freshness']}")
    if issue.details:
        layout.label(text=issue.details)
    for key, item in tuple(dict(issue.evidence).items())[:8]:
        layout.label(text=f"{key}: {json.dumps(item, default=str)[:140]}")
    _actions(layout, context, issue)


def _actions(layout, context, issue):
    row = layout.row(align=True)
    for action, label in (("RECHECK", "Recheck"), ("DISMISS", "Dismiss")):
        operator = row.operator("af.issue_action", text=label)
        operator.action = action; operator.token = issue.id
    for solver in SYSTEM.resolution.available(issue, context):
        operator = layout.operator("af.issue_action", text=solver.label)
        operator.action = "FIX"; operator.token = issue.id; operator.solver = solver.name
    job = SYSTEM.resolution.running.get(issue.id)
    if job:
        layout.label(text="Fix: " + job["state"].replace("_", " ").title())
        if job.get("error"):
            layout.label(text=job["error"])
        _cancel_action(layout, issue, job)


def _cancel_action(layout, issue, job):
    from ..core.issues.resolution import TERMINAL
    if job["state"] not in TERMINAL:
        operator = layout.operator("af.issue_action", text="Cancel fix")
        operator.action = "CANCEL"; operator.token = issue.id
