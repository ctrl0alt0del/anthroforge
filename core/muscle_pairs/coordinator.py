"""Single-flight detector scheduling with debouncing and generation-guarded publication."""
from dataclasses import dataclass
from time import monotonic
from .model import DetectionResult


@dataclass
class Entry:
    scope: object
    settings: object
    generation: int
    due: float
    result: DetectionResult
    backend: object = None
    issues: tuple = ()
    timings: object = None
    context: object = None


class DetectionCoordinator:
    def __init__(self, capture, backend_factory, clock=monotonic, publisher=None, lifecycle=None):
        self.capture, self.factory, self.clock = capture, backend_factory, clock
        self.publisher = publisher
        self.lifecycle = lifecycle
        self.entries, self.active, self.serial, self.epoch = {}, None, 0, 1

    def invalidate(self, key, scope, settings, automatic=True, delay=.150):
        self.serial += 1; generation = self.serial
        previous = self.entries.get(key); backend = previous.backend if previous else None
        if self.active is not None and self.active[0] == key: backend.cancel()
        status = 'queued' if automatic else 'stale'
        self.entries[key] = Entry(scope, settings, generation, self.clock()+delay if automatic else float('inf'),
                                  DetectionResult(generation, status), backend)
        return generation

    def tick(self):
        if self.active is not None: self._poll()
        if self.active is None:
            pending = [(e.due, k) for k, e in self.entries.items() if e.due <= self.clock()]
            if pending: self._start(min(pending)[1])
        return self.active is not None or any(e.due != float('inf') for e in self.entries.values())

    def _start(self, key):
        entry = self.entries[key]; entry.due = float('inf')
        try:
            if hasattr(self.publisher, 'prepare'): self.publisher.prepare(entry.scope)
            if self.lifecycle: self.lifecycle.prepare(entry.scope)
            domains, entry.issues, entry.timings = self.capture.capture(entry.scope, entry.settings)
            if entry.backend is None: entry.backend = self.factory()
            self._submit(entry, domains)
            entry.result = DetectionResult(entry.generation, 'running', issues=entry.issues)
            self.active = key, entry.generation, entry.backend
        except (ValueError, RuntimeError, OSError, ReferenceError) as error:
            status = 'unavailable' if 'UNAVAILABLE' in str(error) else 'failed'
            entry.result = DetectionResult(entry.generation, status, issues=({'message': str(error)},))

    def _submit(self, entry, domains):
        settings = entry.settings
        if self.lifecycle:
            settings, entry.context, timings = self.lifecycle.capture(entry.scope, domains, settings, entry.generation)
            entry.timings.update(timings)
        entry.backend.submit(domains, settings, entry.generation)

    def _publish(self, entry, backend, result):
        if self.lifecycle: self.lifecycle.publish(entry.scope, entry.context, backend, result, self.publisher)
        else: self.publisher(entry.scope, backend, result)

    def _poll(self):
        key, generation, backend = self.active
        try: self._poll_result(key, generation, backend)
        except (ValueError, RuntimeError, OSError, ReferenceError) as error:
            self._failed_backend(key, generation, backend, error)

    def _failed_backend(self, key, generation, backend, error):
        self.active = None; backend.close()
        entry = self.entries.get(key)
        if entry is None: return
        if entry.backend is backend: entry.backend = None
        if entry.generation == generation:
            entry.result = DetectionResult(generation, 'failed', issues=({'message': str(error)},))

    def _poll_result(self, key, generation, backend):
        report = backend.poll()
        if report.state < 2: return
        entry = self.entries.get(key); self.active = None
        backend.release()
        if entry is None or entry.generation != generation: return
        if report.state == 2:
            self._complete(entry, backend, generation)
        else:
            entry.result = DetectionResult(generation, 'cancelled' if report.state == 3 else 'failed',
                                           issues=({'message': report.message.decode()},))

    def _complete(self, entry, backend, generation):
        result = backend.summary(); issues = entry.issues
        if self.publisher:
            try: self._publish(entry, backend, result)
            except (ValueError, RuntimeError, ReferenceError) as error:
                issues = (*issues, {'message': str(error)})
                result.setdefault('stacking', {}).update(status='incomplete', publication='failed')
        stack = result.get('stacking', {})
        if entry.issues: stack.update(status='incomplete', capture_issues=entry.issues)
        entry.result = DetectionResult(generation, 'incomplete' if issues or stack.get('status') == 'incomplete' else 'complete', result['pairs'],
            dict(result['timings'], **entry.timings), issues, geometry_only=not bool(stack), activation_ready=stack.get('publication') == 'published' and stack.get('status') == 'complete', stacking=stack)

    def inspect(self, key):
        entry = self.entries.get(key)
        return entry.result if entry else DetectionResult(0, 'not_scanned')

    def footprint(self, key, index, revision):
        entry = self.entries.get(key)
        if entry is None or revision != (self.epoch, entry.generation): raise ValueError('PAIR_STALE_RESULT')
        if entry.result.status not in ('complete', 'incomplete'): raise ValueError('PAIR_NOT_READY')
        return entry.backend.footprint(index, entry.generation)

    def remove(self, key):
        entry = self.entries.pop(key, None)
        if entry is not None and entry.backend is not None: entry.backend.close()
        if self.active is not None and self.active[0] == key: self.active = None

    def reset(self):
        for key in tuple(self.entries): self.remove(key)
        self.epoch += 1
