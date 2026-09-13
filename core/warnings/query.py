"""Read-only warning protocol port; serialization never evaluates geometry."""
from . import session
from .repository import FILTERS, scope_matches


class WarningQuery:
    def list(self, params=None):
        params, repository = params or {}, session.REPOSITORY
        filters = {key: params[key] for key in FILTERS if key in params}
        total, rows = repository.query(filters, params.get("offset", 0), params.get("limit", 100))
        states = [dict(scope=scope, **value) for scope, value in repository.states.items() if scope_matches(scope, filters)]
        payload = dict(epoch=session.EPOCH, repository_revision=repository.revision, scope=filters,
                       total=total, records=[row.serialize(repository.states[row.entity.scope]["status"], repository.revision) for row in rows])
        payload.update(repository.status(filters), source_scene_revision="unavailable", source_generations=states,
                       check_token=f"{session.EPOCH}:{repository.revision}", telemetry=dict(session.COORDINATOR.metrics))
        return payload

    def feedback(self, request, result, replayed=False):
        if request.get("op") == "warnings.list":
            return dict(result)
        return dict(result, warnings=self.list(dict(limit=0)))
