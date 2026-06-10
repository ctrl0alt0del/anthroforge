try:
    from ...app.use_cases.scp_parenting import mark_active_mesh_as_scp, reparent_scp, set_active_scp_parent
except ImportError:
    from app.use_cases.scp_parenting import mark_active_mesh_as_scp, reparent_scp, set_active_scp_parent


def execute_mark_scp(operator, context):
    return _finish(operator, mark_active_mesh_as_scp(context))


def execute_set_scp_parent(operator, context):
    return _finish(operator, set_active_scp_parent(context))


def execute_reparent_scp(operator, context, child_scp_id, parent_scp_id=""):
    return _finish(operator, reparent_scp(context, child_scp_id, parent_scp_id))


def _finish(operator, result):
    if result.message and operator is not None:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}
