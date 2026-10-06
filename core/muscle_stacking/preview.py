"""A bounded read-only preview, sharing the pipeline but never its publication."""
from time import monotonic, sleep
from ..muscle_pairs import configuration
from ..muscle_pairs.capture import DomainCaptureAdapter
from .native import NativeStackEngine


def preview(scope, change):
    from ..muscle_relationships.preview import configure
    from ..muscle_pairs.runtime import COORDINATOR
    if COORDINATOR.active is not None: raise ValueError('STACK_PREVIEW_BUSY')
    value, groups = configuration.validate(scope[1], {k: v for k, v in change.items() if k != 'relationships'})
    if groups: raise ValueError('STACK_PREVIEW_GROUPING_REQUIRES_CONFIGURATION')
    settings = configuration.from_values(value)
    domains, issues, capture_time = capture_readonly(scope, settings)
    settings = configure(scope[1], change, domains, settings)
    with NativeStackEngine() as engine:
        engine.submit(domains, settings, 1); finish(engine); result = engine.summary()
        result.update(capture_time, issues=issues, publication='preview_only')
        result['surfaces'] = [dict(domain=key.__dict__, vertices=points.tolist()) for key, points in engine.surfaces().items()]
    return result


def finish(engine):
    deadline = monotonic()+120
    while engine.poll().state < 2:
        if monotonic() > deadline: engine.cancel(); raise ValueError('STACK_PREVIEW_TIMEOUT')
        sleep(.005)
    engine.release()


def capture_readonly(scope, settings):
    from . import publication
    previous = publication.RECOVER; publication.RECOVER = False
    try: return DomainCaptureAdapter().capture(scope, settings)
    finally: publication.RECOVER = previous
