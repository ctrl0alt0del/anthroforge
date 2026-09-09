"""Coverage request over compatible calibrated views."""
from ...core.authoring.errors import require
from ...core.authoring.visual_coverage import report
from .visual import load_view


def coverage(service, request):
    loaded = [load_view(service, identity) for identity in request['params']['view_ids']]
    require(len({v['snapshot_id'] for v, _ in loaded}) == 1, 'VISUAL_SNAPSHOT_MISMATCH')
    return dict(coverage=report(loaded[0][1], [v for v, _ in loaded]))
