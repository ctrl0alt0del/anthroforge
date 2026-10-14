"""Read-only projections and registered navigation; never runs diagnostics."""


class Presentation:
    def __init__(self, repository):
        self.repository, self.targets, self.dismissed = repository, {}, set()

    def register_target(self, kind, select):
        if kind in self.targets:
            raise ValueError("Duplicate issue target handler")
        self.targets[kind] = select
        return lambda: self.targets.pop(kind, None)

    def select(self, identity, context):
        issue = self.repository.records.get(identity)
        callback = None if issue is None else self.targets.get(issue.entity.kind)
        return bool(callback and callback(issue, context))

    def dismiss(self, identity):
        self.dismissed.add(identity)
        self.repository.changed()

    def rows(self, filters=None, offset=0, limit=100):
        total, rows = self.repository.query(filters, offset, limit)
        return total, tuple(self.serialize(row) for row in rows)

    def serialize(self, row):
        state = self.repository.provider_states.get((row.entity.scope, row.provider), {}).get("status", "UNSCANNED")
        return dict(row.serialize(state, self.repository.revision), dismissed=row.id in self.dismissed)
