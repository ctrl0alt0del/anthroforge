"""World-space guesses become native SCP attachments, without editing the scene."""
from ...core.authoring.errors import require


def snap_points(service, request):
    service.check(request['params'])
    picker = getattr(service.scene, 'snap_points', None)
    require(callable(picker), 'UNSUPPORTED_CAPABILITY', 'Native surface point picking is unavailable.')
    hits = picker(request['params'], service.inventory)
    diagnostics = [diagnostic for hit in hits for diagnostic in hit['diagnostics']]
    return dict(hits=hits, diagnostics=diagnostics, status='unresolved' if diagnostics else 'success')
