"""Legacy defaults over the single generic repository implementation."""
from ..issues.repository import IssueRepository, FILTERS, STATES, fields, sort_key, scope_matches


class WarningRepository(IssueRepository):
    def state(self, scope, status, generation=0, error="", provider="fiber_hard_anchor.v1"):
        return super().state(scope, status, generation, error, provider)

    def replace(self, scope, records, generation=0, metadata=None, provider="fiber_hard_anchor.v1"):
        return super().replace(scope, records, generation, metadata, provider)
